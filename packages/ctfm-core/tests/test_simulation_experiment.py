"""Synthetic integration fixtures; these are not measured device results."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from ctfm.measurement import PARSER_VERSION, DEFAULTS
from ctfm.profiles import build_profile,publish_profile
from ctfm.simulation import run_experiment
from ctfm.simulation.torch_runner import create_model


def synthetic_profile():
    sha='a'*64
    source=dict(file_id='synthetic-pulse',sha256=sha,filename='synthetic.csv',sheet=None,device_id='fixture-device',condition_id='SYNTHETIC',columns={'time_s':'t','vgs_v':'v','id_a':'i'},units={'time_s':'s','vgs_v':'V','id_a':'A'},read_vgs_v=0,vds_v=.1,direction='ltp',source_rows=list(range(1,12)))
    states=[]
    for i,g in enumerate([1e-5,2e-5,4e-5,5e-5]):
        row=i+3
        sid=hashlib.sha256(json.dumps([sha,None,row,PARSER_VERSION],separators=(',',':')).encode()).hexdigest()
        states.append(dict(state_id=sid,source_id='synthetic-pulse',source_row=row,transition_row=row+2,time_s=6.+i,direction='ltp',pulse_step=None,extraction_index=i+1,id_a=g*.1,vgs_v=0.,conductance_s=g,selected=True,exclusion_reason=None))
    analysis=dict(kind='pulse_states',condition_id='SYNTHETIC',states=states,provenance=[source],settings=dict(DEFAULTS))
    d2d=dict(kind='d2d',condition_id='SYNTHETIC',d2d=dict(status='available',cv=.1,source_kind='iv_proxy',physical_device_count=2,matched_conditions=1,distribution='assumed_lognormal',analysis_id=None,assumption_ids=['d2d_lognormal']))
    fit=dict(a=3e-6,b=-.5e-6,rmse=0.,r_squared=1.,n=3,time_min_s=10.,time_max_s=100.)
    retention=dict(kind='retention',condition_id='SYNTHETIC',retention=dict(status='available',program_fit=fit,erase_fit=fit,read_vgs_v=0.,vds_v=.1,source_label='synthetic fixture'))
    p=build_profile('SYNTHETIC',analysis,[s['state_id'] for s in states],d2d,retention,display_name='SYNTHETIC ONLY')
    p['manifest']=publish_profile(p['manifest'],p['states'],'synthetic test','Synthetic numerical validation only; no device measurement')
    return p


def configuration(p,effects=False):
    return dict(schema_version='1.2.0',profile_refs=[dict(id=p['manifest']['profile_id'],revision=1)],model_id='mnist_mlp_v1',checkpoint_id=None,pools=['combined','common'],mappings=['fixed_reference'],effects=dict(d2d=effects,retention=effects,adc=effects,c2c=False),arrays=2 if effects else 1,n_reprogram=1,years=[0,1] if effects else [0],seed=20260917,hardware=dict(tile_size=128,adc_bits=6 if effects else None,adc_order='subtract_then_adc' if effects else None,range_policy='validation_max_abs' if effects else None,preset_id=None),engines=dict(accuracy='torch_reference',ppa='off'))


def c2c_configuration(p,*,cv_percent=5,n_reprogram=2,arrays=2,years=None,adc_order=None,d2d=True):
    """A 1.3.0 request isolated to C2C: single pool/mapping so array/reprogram
    identity is easy to track directly from run_id in tests."""
    years=[0] if years is None else years
    return dict(schema_version='1.3.0',
               profile_refs=[dict(id=p['manifest']['profile_id'],revision=1,c2c=dict(cv_percent=cv_percent,source='manual_assumption'))],
               model_id='mnist_mlp_v1',checkpoint_id=None,pools=['combined'],mappings=['fixed_reference'],
               effects=dict(d2d=d2d,retention=len(years)>1,adc=adc_order is not None,c2c=True),
               arrays=arrays if d2d else 1,n_reprogram=n_reprogram,years=years,seed=20260917,
               hardware=dict(tile_size=64,adc_bits=6 if adc_order else None,adc_order=adc_order,
                             range_policy='validation_max_abs' if adc_order else None,preset_id=None),
               engines=dict(accuracy='torch_reference',ppa='off'))


def synthetic_data():
    train=np.zeros((60000,784),dtype=np.uint8);test=np.zeros((10000,784),dtype=np.uint8)
    return (train,np.zeros(60000,dtype=np.uint8),test,np.zeros(10000,dtype=np.uint8),[{'synthetic':True}])


class ExperimentIntegrationTests(unittest.TestCase):
    def test_synthetic_full_artifacts_invalid_denominators_and_checkpoint_reuse(self):
        p=synthetic_profile();config=configuration(p,True)
        train=np.zeros((60000,784),dtype=np.uint8);test=np.zeros((10000,784),dtype=np.uint8)
        data=(train,np.zeros(60000,dtype=np.uint8),test,np.zeros(10000,dtype=np.uint8),[{'synthetic':True}])
        with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist',return_value=data),patch('ctfm.simulation.train_model',return_value=(create_model(),[])):
            root=Path(directory)
            r=run_experiment(config,[p],root/'first',cache_dir=root/'cache')
            self.assertTrue((root/'first'/'checkpoint.pt').is_file())
            self.assertTrue((root/'first'/'candidate-1-calibration.json').is_file())
            self.assertEqual(r['summary']['skipped'],4)
            self.assertEqual(r['status'],'partial')
            self.assertEqual({k:r['summary'][k] for k in ('requested','completed','failed','skipped')},dict(requested=8,completed=2,failed=2,skipped=4))
            self.assertEqual(r['runs'][0]['engine'],'torch_reference')
            self.assertIsNone(r['runs'][0]['profile_ref'])
            # D0 is FP32 digital, D1 is the same digital weights with unsigned 8 bit
            # activations, so their gap is the input quantization loss on its own.
            self.assertEqual([r['runs'][0]['kind'],r['runs'][1]['kind']],['D0','D1'])
            self.assertEqual(r['runs'][1]['engine'],'torch_reference')
            self.assertIsNotNone(r['runs'][1]['accuracy'])
            self.assertEqual(r['runs'][2]['profile_ref'],config['profile_refs'][0])
            self.assertEqual(r['runs'][2]['ppa']['status'],'unsupported')
            # The refusal must come from the adapter, carrying why it refused and
            # how the two models differ, with no number standing in for absence.
            ppa=r['runs'][2]['ppa']
            self.assertTrue(ppa['reason'])
            self.assertTrue(ppa['reasons'] if 'reasons' in ppa else ppa['model_mismatches'])
            self.assertIn('nonuniform_states',{m['id'] for m in ppa['model_mismatches']})
            self.assertEqual(ppa['preset']['status'],'unsupported')
            for key in ('area_m2','energy_j_per_inference','latency_s_per_inference','raw_output'):
                self.assertIsNone(ppa[key])
            self.assertTrue(r['runs'][2]['mapping_errors'])
            self.assertIsNone(r['runs'][2]['hardware']['adc_bits'])
            self.assertEqual(r['runs'][3]['hardware']['adc_bits'],6)
            self.assertEqual(r['runs'][3]['hardware']['adc_order'],'subtract_then_adc')
            self.assertEqual(r['effective_config']['input_encoding']['bits'],8)
            self.assertEqual(r['schema_version'],'1.2.0')
            self.assertEqual(r['summary']['failed'],2)
            zero,one=r['summary']['array_statistics']
            self.assertEqual(zero['accuracy']['n'],2);self.assertIsNone(one['accuracy']['mean'])
            self.assertEqual(one['invalid_arrays'],2)
            self.assertEqual(r['requested_config'],config)
            config['checkpoint_id']=r['checkpoint_id'].upper()
            config['profile_refs'][0]['id']=config['profile_refs'][0]['id'].upper()
            config['profile_refs'][0]['revision']=1.0
            for key in ('seed','arrays','n_reprogram'):config[key]=float(config[key])
            for key in ('tile_size','adc_bits'):config['hardware'][key]=float(config['hardware'][key])
            r2=run_experiment(config,[p],root/'second',cache_dir=root/'cache',checkpoint_path=root/'first'/'checkpoint.pt')
            self.assertEqual(r2['checkpoint_id'],r['checkpoint_id'])
            self.assertEqual(r2['requested_config'],config)
            self.assertIsInstance(r2['effective_config']['seed'],int)
            self.assertIsInstance(r2['effective_config']['hardware']['adc_bits'],int)
            self.assertEqual(r2['resolved_config']['profile_refs'][0]['id'],p['manifest']['profile_id'])
            self.assertEqual([v.get('accuracy') for v in r2['runs']],[v.get('accuracy') for v in r['runs']])
            with self.assertRaisesRegex(ValueError,'Checkpoint metadata mismatch: split_seed'):
                run_experiment(config,[p],root/'changed-split',cache_dir=root/'cache',checkpoint_path=root/'first'/'checkpoint.pt',split_seed=7)
            config['checkpoint_id']='00000000-0000-4000-8000-000000000000'
            with self.assertRaisesRegex(ValueError,'Checkpoint metadata mismatch'):
                run_experiment(config,[p],root/'third',cache_dir=root/'cache',checkpoint_path=root/'first'/'checkpoint.pt')
    def test_missing_cv_is_rejected_before_data_download(self):
        p=synthetic_profile();p['manifest']['d2d']['cv']=None
        from ctfm.profiles import compute_profile_hash
        p['manifest']['profile_hash']=compute_profile_hash(p['manifest'])
        with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
            with self.assertRaises(ValueError):run_experiment(configuration(p,True),[p],Path(directory),cache_dir=Path(directory)/'cache')
            download.assert_not_called()


class C2CIntegrationTests(unittest.TestCase):
    """C2C wiring: run_experiment end to end with mocked MNIST/training, same
    pattern as ExperimentIntegrationTests above. Not a measured-device claim."""

    def _run(self,config,p,directory,name='run'):
        with patch('ctfm.simulation.load_mnist',return_value=synthetic_data()),patch('ctfm.simulation.train_model',return_value=(create_model(),[])):
            return run_experiment(config,[p],Path(directory)/name,cache_dir=Path(directory)/'cache')

    def test_c2c_on_with_cv_zero_matches_c2c_off_exactly(self):
        p=synthetic_profile()
        off=configuration(p,False)
        on=c2c_configuration(p,cv_percent=0,n_reprogram=3,arrays=1,d2d=False)
        with tempfile.TemporaryDirectory() as directory:
            r_off=self._run(off,p,directory,'off');r_on=self._run(on,p,directory,'on')
            all_off=[r for r in r_off['runs'] if r['kind']=='ALL'];all_on=[r for r in r_on['runs'] if r['kind']=='ALL']
            self.assertEqual(len(all_off),1);self.assertEqual(len(all_on),3)
            for r in all_on:self.assertEqual(r['accuracy'],all_off[0]['accuracy'])

    def test_different_reprograms_draw_different_c2c_records(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=8,n_reprogram=2,arrays=1,d2d=False)
        with tempfile.TemporaryDirectory() as directory:
            r=self._run(config,p,directory)
            runs=[x for x in r['runs'] if x['kind']=='ALL']
            self.assertEqual(len(runs),2)
            seeds0={v['seed'] for v in runs[0]['c2c_diagnostics'].values()}
            seeds1={v['seed'] for v in runs[1]['c2c_diagnostics'].values()}
            self.assertTrue(seeds0.isdisjoint(seeds1))
            self.assertEqual(runs[0]['run_id'],'candidate-1-array-0-record-0-year-0')
            self.assertEqual(runs[1]['run_id'],'candidate-1-array-0-record-1-year-0')
            self.assertTrue((Path(directory)/'run'/'candidate-1-array-0-record-0.json').is_file())

    def test_d2d_diagnostics_are_identical_across_reprograms_of_the_same_array(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=8,n_reprogram=2,arrays=1,d2d=True)
        with tempfile.TemporaryDirectory() as directory:
            r=self._run(config,p,directory)
            runs=[x for x in r['runs'] if x['kind']=='ALL']
            self.assertEqual(runs[0]['d2d_diagnostics'],runs[1]['d2d_diagnostics'])
            self.assertNotEqual(runs[0]['c2c_diagnostics'],runs[1]['c2c_diagnostics'])

    def test_the_same_record_is_reused_across_retention_years(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=8,n_reprogram=1,arrays=1,d2d=False,years=[0,1])
        with tempfile.TemporaryDirectory() as directory:
            r=self._run(config,p,directory)
            runs=[x for x in r['runs'] if x['kind']=='ALL']
            self.assertEqual({x['years'] for x in runs},{0,1})
            diag_by_year={x['years']:x['c2c_diagnostics'] for x in runs}
            self.assertEqual(diag_by_year[0],diag_by_year[1])

    def test_the_same_record_is_reused_across_adc_orders_via_shared_checkpoint(self):
        p=synthetic_profile()
        config_a=c2c_configuration(p,cv_percent=8,n_reprogram=1,arrays=1,d2d=False,adc_order='subtract_then_adc')
        with tempfile.TemporaryDirectory() as directory:
            r1=self._run(config_a,p,directory,'a')
            config_b=deepcopy(config_a)
            config_b['checkpoint_id']=r1['checkpoint_id']
            config_b['hardware']['adc_order']='adc_then_subtract'
            with patch('ctfm.simulation.load_mnist',return_value=synthetic_data()),patch('ctfm.simulation.train_model',return_value=(create_model(),[])):
                r2=run_experiment(config_b,[p],Path(directory)/'b',cache_dir=Path(directory)/'cache',checkpoint_path=Path(directory)/'a'/'checkpoint.pt')
            diag_a=[x for x in r1['runs'] if x['kind']=='ALL'][0]['c2c_diagnostics']
            diag_b=[x for x in r2['runs'] if x['kind']=='ALL'][0]['c2c_diagnostics']
            self.assertEqual(diag_a,diag_b)

    def test_same_config_reproduces_identical_c2c_results(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=6,n_reprogram=2,arrays=2,d2d=True)
        with tempfile.TemporaryDirectory() as directory:
            r1=self._run(config,p,directory,'r1')
            config2=deepcopy(config);config2['checkpoint_id']=r1['checkpoint_id']
            with patch('ctfm.simulation.load_mnist',return_value=synthetic_data()),patch('ctfm.simulation.train_model',return_value=(create_model(),[])):
                r2=run_experiment(config2,[p],Path(directory)/'r2',cache_dir=Path(directory)/'cache',checkpoint_path=Path(directory)/'r1'/'checkpoint.pt')
            all1=[x for x in r1['runs'] if x['kind']=='ALL'];all2=[x for x in r2['runs'] if x['kind']=='ALL']
            self.assertEqual([x['accuracy'] for x in all1],[x['accuracy'] for x in all2])
            self.assertEqual([x['c2c_diagnostics'] for x in all1],[x['c2c_diagnostics'] for x in all2])

    def test_array_statistics_distinguish_array_from_reprogram_variance(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=6,n_reprogram=3,arrays=2,d2d=True)
        with tempfile.TemporaryDirectory() as directory:
            r=self._run(config,p,directory)
            stats=r['summary']['array_statistics'][0]
            self.assertEqual(stats['requested_arrays'],2);self.assertEqual(stats['requested_reprogram'],3)
            # One value per array (its mean across reprograms), never one per record.
            self.assertEqual(stats['accuracy']['n'],2)
            self.assertEqual(set(stats['reprogram_accuracy_by_array']),{'0','1'})
            for per_array in stats['reprogram_accuracy_by_array'].values():self.assertEqual(per_array['n'],3)

    def test_reprogram_and_array_interpretation_text_are_not_swapped(self):
        """04_REVIEW: the per-array reprogram entry must not carry summarize()'s
        default 'across seeded arrays' wording -- it is a within-array,
        across-reprogram distribution. The top-level accuracy must say it is
        built from each array's own reprogram mean, not one sample per record."""
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=6,n_reprogram=3,arrays=2,d2d=True)
        with tempfile.TemporaryDirectory() as directory:
            r=self._run(config,p,directory)
            stats=r['summary']['array_statistics'][0]
            self.assertIn('own mean',stats['accuracy']['interpretation'])
            self.assertNotEqual(stats['accuracy']['interpretation'],'distribution across seeded arrays, not a confidence interval')
            for array_index,entry in stats['reprogram_accuracy_by_array'].items():
                self.assertIn(f'array_index={array_index}',entry['interpretation'])
                self.assertIn('reprograms of this one array',entry['interpretation'])
                self.assertNotIn('seeded arrays',entry['interpretation'])

    def test_off_path_array_statistics_has_no_reprogram_breakdown(self):
        p=synthetic_profile()
        config=configuration(p,True)
        with tempfile.TemporaryDirectory() as directory:
            r=self._run(config,p,directory)
            for stats in r['summary']['array_statistics']:
                self.assertIsNone(stats['reprogram_accuracy_by_array']);self.assertEqual(stats['requested_reprogram'],1)
                # Off path keeps summarize()'s original, unmodified default text.
                self.assertEqual(stats['accuracy']['interpretation'],'distribution across seeded arrays, not a confidence interval')

    def test_c2c_run_budget_includes_n_reprogram(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=5,n_reprogram=100,arrays=21,d2d=True)  # 21*100=2100 > 2000
        with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
            with self.assertRaisesRegex(ValueError,'budget'):run_experiment(config,[p],Path(directory),cache_dir=Path(directory)/'cache')
            download.assert_not_called()

    def test_invalid_c2c_cv_is_rejected_before_data_download(self):
        p=synthetic_profile()
        base=c2c_configuration(p,cv_percent=5,n_reprogram=2,arrays=1,d2d=False)
        for bad in (None,-1,float('nan'),float('inf'),True):
            config=deepcopy(base);config['profile_refs'][0]['c2c']['cv_percent']=bad
            with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
                with self.assertRaises(ValueError):run_experiment(config,[p],Path(directory),cache_dir=Path(directory)/'cache')
                download.assert_not_called()

    def test_c2c_missing_or_wrong_source_is_rejected(self):
        p=synthetic_profile()
        base=c2c_configuration(p,cv_percent=5,n_reprogram=2,arrays=1,d2d=False)
        no_c2c=deepcopy(base);del no_c2c['profile_refs'][0]['c2c']
        wrong_source=deepcopy(base);wrong_source['profile_refs'][0]['c2c']['source']='measured'
        for config in (no_c2c,wrong_source):
            with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
                with self.assertRaises(ValueError):run_experiment(config,[p],Path(directory),cache_dir=Path(directory)/'cache')
                download.assert_not_called()

    def test_invalid_n_reprogram_is_rejected(self):
        p=synthetic_profile()
        base=c2c_configuration(p,cv_percent=5,n_reprogram=2,arrays=1,d2d=False)
        for bad in (0,101,1.5,True):
            config=deepcopy(base);config['n_reprogram']=bad
            with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
                with self.assertRaises(ValueError):run_experiment(config,[p],Path(directory),cache_dir=Path(directory)/'cache')
                download.assert_not_called()
        off_but_reprogrammed=configuration(p,False);off_but_reprogrammed['n_reprogram']=2
        with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
            with self.assertRaises(ValueError):run_experiment(off_but_reprogrammed,[p],Path(directory),cache_dir=Path(directory)/'cache')
            download.assert_not_called()

    def test_c2c_on_requires_schema_1_3(self):
        p=synthetic_profile()
        config=c2c_configuration(p,cv_percent=5,n_reprogram=1,arrays=1,d2d=False)
        config['schema_version']='1.2.0'
        with tempfile.TemporaryDirectory() as directory,patch('ctfm.simulation.load_mnist') as download:
            with self.assertRaises(ValueError):run_experiment(config,[p],Path(directory),cache_dir=Path(directory)/'cache')
            download.assert_not_called()

if __name__=='__main__':unittest.main()
