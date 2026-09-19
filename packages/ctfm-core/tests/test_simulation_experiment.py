"""Synthetic integration fixtures; these are not measured device results."""
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
    return dict(schema_version='1.1.0',profile_refs=[dict(id=p['manifest']['profile_id'],revision=1)],model_id='mnist_mlp_v1',checkpoint_id=None,pools=['combined','common'],mappings=['fixed_reference'],effects=dict(d2d=effects,retention=effects,adc=effects,c2c=False),arrays=2 if effects else 1,n_reprogram=1,years=[0,1] if effects else [0],seed=20260917,hardware=dict(tile_size=128 if effects else None,adc_bits=6 if effects else None,range_policy='validation_max_abs' if effects else None,preset_id=None),engines=dict(accuracy='torch_reference',ppa='off'))


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
            self.assertEqual(r['runs'][1]['profile_ref'],config['profile_refs'][0])
            self.assertEqual(r['runs'][1]['ppa']['status'],'unsupported')
            # The refusal must come from the adapter, carrying why it refused and
            # how the two models differ, with no number standing in for absence.
            ppa=r['runs'][1]['ppa']
            self.assertTrue(ppa['reason'])
            self.assertTrue(ppa['reasons'] if 'reasons' in ppa else ppa['model_mismatches'])
            self.assertIn('nonuniform_states',{m['id'] for m in ppa['model_mismatches']})
            self.assertEqual(ppa['preset']['status'],'unsupported')
            for key in ('area_m2','energy_j_per_inference','latency_s_per_inference','raw_output'):
                self.assertIsNone(ppa[key])
            self.assertTrue(r['runs'][1]['mapping_errors'])
            self.assertIsNone(r['runs'][1]['hardware']['adc_bits'])
            self.assertEqual(r['runs'][2]['hardware']['adc_bits'],6)
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

if __name__=='__main__':unittest.main()
