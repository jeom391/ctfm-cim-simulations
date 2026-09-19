"""Regression tests for independently reviewed scientific input boundaries."""
import copy
import unittest
from ctfm.measurement import analyze
from ctfm.profiles import build_profile,validate_profile,compute_profile_hash
from test_measurement_profiles import dataset,pulse


class ScientificReviewTests(unittest.TestCase):
    def shared_iv(self):
        erase=dataset([(-1,0),(0,2e-6),(1,0)],'iv',branch='erase',sweep_amplitude_v=1,file_id='shared',sha256='a'*64)
        program=dataset([(1,0),(0,1e-6),(-1,2e-6)],'iv',branch='program',sweep_amplitude_v=1,file_id='shared',sha256='a'*64,source_rows=[4,5,6])
        return [erase,program]

    def test_shared_file_iv_crossing_can_be_selected_per_input(self):
        inputs=self.shared_iv();first=analyze('iv',inputs,{})
        rows=first['tables']['vth'];keys=[r['selection_key'] for r in rows]
        self.assertNotEqual(*keys)
        self.assertEqual(keys,[p['selection_key'] for p in first['provenance']])
        selected=analyze('iv',inputs,{'crossing_segments':{keys[0]:{'source_rows':[2,3],'reason':'Choose first erase crossing'}}})
        self.assertEqual([r['status'] for r in selected['tables']['vth']],['ok','ok'])
        self.assertAlmostEqual(selected['tables']['vth'][0]['vth_v'],-.5)
        self.assertEqual(selected['tables']['memory_window'][0]['mw_v'],.5)
        self.assertEqual([r['selection_key'] for r in selected['tables']['vth']],keys)
        with self.assertRaisesRegex(ValueError,'(?i)ambiguous.*file_id|file_id.*ambiguous'):
            analyze('iv',inputs,{'crossing_segments':{'shared':{'source_rows':[2,3],'reason':'Legacy key is ambiguous'}}})

    def test_shared_file_d2d_selections_distinguish_device_columns(self):
        base=dataset([(-1,1e-6),(0,1e-6),(0,1e-6),(1,1e-6)],'d2d',file_id='shared',sha256='b'*64,branch='erase',sweep_amplitude_v=1)
        base['rows']=[dict(v=v,i1=1e-6,i2=3e-6) for v in [-1,0,0,1]]
        first=copy.deepcopy(base);first['column_mapping']={'vgs_v':'v','id_a':'i1'}
        second=copy.deepcopy(base);second['device_id']='D2';second['column_mapping']={'vgs_v':'v','id_a':'i2'}
        r=analyze('d2d',[first,second],{})
        device_rows=r['tables']['d2d_conditions'][0]['device_values']
        keys=[row['selection_key'] for row in device_rows]
        self.assertNotEqual(*keys)
        choices={keys[0]:dict(source_rows=[2,3],reason='First boundary'),keys[1]:dict(source_rows=[4,5],reason='Last boundary')}
        selected=analyze('d2d',[first,second],{'crossing_segments':choices})
        self.assertEqual(selected['d2d']['status'],'available')
        self.assertAlmostEqual(selected['d2d']['cv'],2**-.5)

    def test_no_interpolation_between_nonadjacent_source_rows(self):
        d=dataset([(-1,0),(1,2e-6)],'iv',branch='erase',sweep_amplitude_v=1,source_rows=[2,20])
        r=analyze('iv',[d],{})['tables']['vth'][0]
        self.assertEqual(r['status'],'no_crossing');self.assertIsNone(r['vth_v'])
        d['rows'][0]['id_a']=1e-6
        r=analyze('iv',[d],{})['tables']['vth'][0]
        self.assertEqual(r['status'],'ok');self.assertEqual(r['vth_v'],-1)

    def retention_profile(self):
        states=analyze('pulse_states',[pulse()],{})
        retention=analyze('retention',[dataset([(10,9e-6,4e-6),(100,8e-6,3e-6),(1000,7e-6,2e-6)],'retention',file_id='ret',source_label='R1',sheet='Raw Data')],{})
        return build_profile('A1',states,[s['state_id'] for s in states['states']],retention_analysis=retention)

    def test_imported_retention_cannot_override_approved_source_or_reference(self):
        p=self.retention_profile()
        for changes in [dict(source_label='R3(2)'),dict(source_label='R2'),dict(read_vgs_v=.5),dict(reference_time_s=100),dict(program_reference_current_a=-1),dict(simulation_available=False)]:
            with self.subTest(changes=changes):
                m=copy.deepcopy(p['manifest']);m['retention'].update(changes);m['profile_hash']=compute_profile_hash(m)
                with self.assertRaises(ValueError):validate_profile(m,p['states'])
        validate_profile(p['manifest'],p['states'])

if __name__=='__main__':unittest.main()
