import copy
import hashlib
import io
import math
import unittest
from ctfm.measurement import analyze, parse_table
from ctfm.profiles import build_profile, publish_profile, validate_profile, states_csv, parse_states_csv


def dataset(rows, kind='pulse_states', **kw):
    keys = {'pulse_states':['time_s','id_a','vgs_v'], 'iv':['vgs_v','id_a'], 'd2d':['vgs_v','id_a'], 'retention':['time_s','program_id_a','erase_id_a']}[kind]
    d = dict(file_id='f1',sha256='a'*64,filename='raw.csv',sheet=None,rows=[dict(zip(keys,r)) for r in rows],source_rows=list(range(2,len(rows)+2)),column_mapping={k:k for k in keys},units={k:('s' if k=='time_s' else 'V' if k=='vgs_v' else 'A') for k in keys},device_id='D1',condition_id='A1',read_vgs_v=0,vds_v=.1)
    d.update(kw)
    if 'sha256' not in kw: d['sha256']=hashlib.sha256(repr((rows,kw)).encode()).hexdigest()
    return d


def pulse(direction='ltp', values=(1e-6,2e-6), **kw):
    sign=-1 if direction=='ltp' else 1
    rows=[]
    for n,val in enumerate(values):
        t=6+n*5
        rows.extend([(t,val,0),(t+1,val*2,0),(t+2,0,sign),(t+3,0,sign*6)])
    rows.extend([(6+len(values)*5,3e-6,0),(7+len(values)*5,3e-6,0)])
    return dataset(rows,direction=direction,**kw)


class MeasurementTests(unittest.TestCase):
    def test_csv_encoding_source_rows_and_bad_extension(self):
        p=parse_table('기기 메모\n시간,전류,전압\n6,1e-6,0\n7,2e-6,0\n'.encode('cp949'),'raw.csv')
        self.assertEqual(p['columns'],['시간','전류','전압'])
        self.assertEqual(p['source_rows'],[3,4])
        with self.assertRaises(ValueError): parse_table(b'', 'legacy.xls')
        with self.assertRaises(ValueError): parse_table(b'', '~$raw.xlsx')

    def test_xlsx_uncached_formula_is_rejected(self):
        from openpyxl import Workbook
        wb=Workbook(); ws=wb.active; ws.append(['t','i']); ws.append([6,'=1+1'])
        buf=io.BytesIO(); wb.save(buf)
        with self.assertRaisesRegex(ValueError,'cached|cache'): parse_table(buf.getvalue(),'raw.xlsx',ws.title)

    def test_ramp_start_j_minus_two_and_no_offset(self):
        r=analyze('pulse_states',[pulse()],{})
        self.assertEqual([s['source_row'] for s in r['states']],[2,6])
        self.assertEqual([s['transition_row'] for s in r['states']],[4,8])
        for state,want in zip(r['states'],[1e-5,2e-5]): self.assertAlmostEqual(state['conductance_s'],want)
        self.assertTrue(all(s['pulse_step'] is None for s in r['states']))
        self.assertTrue(any(e['reason']=='no_next_transition' for e in r['exclusions']))
        self.assertEqual(r['settings']['sample_offset_rows'],2)

    def test_pulse_boundary_polarity_and_nonpositive(self):
        d=pulse(values=(-1e-6,2e-6)); d['rows'][0]['time_s']=5.999
        r=analyze('pulse_states',[d],{})
        self.assertEqual(len(r['states']),1)
        self.assertTrue(any(e['reason']=='before_start_time' for e in r['exclusions']))
        r=analyze('pulse_states',[pulse(values=(-1e-6,2e-6))],{})
        self.assertFalse(r['states'][0]['selected'])
        bad=pulse(); bad['direction']='ltd'
        with self.assertRaisesRegex(ValueError,'polarity'): analyze('pulse_states',[bad],{})

    def test_units_time_reversal_nonfinite_and_missing_mapping(self):
        d=pulse(); d['units']['id_a']='uA'
        for row in d['rows']: row['id_a']*=1e6
        self.assertAlmostEqual(analyze('pulse_states',[d],{})['states'][0]['conductance_s'],1e-5)
        for value in [None,float('nan'),'abc']:
            bad=pulse(); bad['rows'][0]['id_a']=value
            with self.assertRaises(ValueError): analyze('pulse_states',[bad],{})
        bad=pulse(); bad['rows'][1]['time_s']=1
        with self.assertRaises(ValueError): analyze('pulse_states',[bad],{})
        bad=pulse(); del bad['units']['id_a']
        with self.assertRaises(ValueError): analyze('pulse_states',[bad],{})

    def test_ccm_exact_interpolation_plateau_and_multiple(self):
        for points, status, value in [([(-1,0),(1,2e-6)],'ok',0), ([(0,1e-6),(1,2e-6)],'ok',0), ([(0,1e-6),(1,1e-6)],'ambiguous_crossing',None), ([(-1,0),(0,2e-6),(1,0)],'ambiguous_crossing',None), ([(-1,0),(1,0)],'no_crossing',None)]:
            d=dataset(points,'iv',branch='erase',sweep_amplitude_v=1)
            row=analyze('iv',[d],{})['tables']['vth'][0]
            self.assertEqual(row['status'],status); self.assertEqual(row['vth_v'],value)
        d=dataset([(-1,0),(0,2e-6),(1,0)],'iv',branch='erase',sweep_amplitude_v=1)
        r=analyze('iv',[d],{'crossing_segments':{'f1':{'source_rows':[2,3],'reason':'reviewed first crossing'}}})
        self.assertEqual(r['tables']['vth'][0]['vth_v'],-.5)

    def test_memory_window_is_mean_of_device_absolute_differences(self):
        datasets=[]
        for dev,p,e in [('D1',2,0),('D2',0,2)]:
            for branch,v in [('program',p),('erase',e)]:
                points=[(v-1,0),(v+1,2e-6)]
                if branch=='program': points.reverse()
                datasets.append(dataset(points,'iv',device_id=dev,branch=branch,sweep_amplitude_v=3,file_id=dev+branch))
        row=analyze('iv',datasets,{})['tables']['by_amplitude'][0]
        self.assertEqual(row['mw_mean_v'],2)
        self.assertEqual(row['program_vth_mean_v'],1)
        self.assertEqual(row['erase_vth_mean_v'],1)

    def test_d2d_n_two_and_cv_rms(self):
        ds=[]
        for amp,currents in [(1,(1e-6,3e-6)),(2,(2e-6,2e-6))]:
            for dev,current in zip(['D1','D2'],currents):
                ds.append(dataset([(-1,current),(1,current)],'d2d',device_id=dev,file_id=dev+str(amp),branch='erase',sweep_amplitude_v=amp))
        r=analyze('d2d',ds,{})
        self.assertAlmostEqual(r['d2d']['cv'],.5)
        self.assertEqual(r['d2d']['physical_device_count'],2)
        self.assertEqual(r['d2d']['matched_conditions'],2)
        with self.assertRaises(ValueError): analyze('d2d',[ds[0],ds[0]],{})
        ds[1]['read_vgs_v']=.5
        bad=analyze('d2d',ds,{})
        self.assertTrue(any(e['reason']=='read_condition_mismatch' for e in bad['exclusions']))

    def test_retention_raw_log_fit_and_exclusions(self):
        d=dataset([(1,999,999),(10,9e-6,4e-6),(100,8e-6,3e-6),(1000,7e-6,2e-6)],'retention',source_label='R1',sheet='Raw Data')
        r=analyze('retention',[d],{})
        fit=r['retention']['program_fit']
        self.assertAlmostEqual(fit['a'],10e-6); self.assertAlmostEqual(fit['b'],-1e-6)
        self.assertEqual(fit['n'],3); self.assertAlmostEqual(fit['r_squared'],1)
        self.assertTrue(any(e['reason']=='before_fit_start' for e in r['exclusions']))
        d['sheet']='Normalized Data'
        with self.assertRaises(ValueError): analyze('retention',[d],{})


class ProfileTests(unittest.TestCase):
    def result(self, ltd_values=(2e-6,3e-6)):
        return analyze('pulse_states',[pulse(),pulse('ltd',ltd_values,file_id='f2',sha256='b'*64)],{})

    def test_duplicate_g_sources_preserved_common_no_fabricated_bounds(self):
        r=self.result(); p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        self.assertEqual(len(p['states']),4)
        self.assertFalse(p['manifest']['pools']['common']['available'])
        self.assertEqual(p['manifest']['c2c']['cv'],None)
        self.assertEqual(p['manifest']['c2c']['status'],'unavailable')
        r=self.result((1.5e-6,3e-6)); p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        pool=p['manifest']['pools']['common']
        self.assertTrue(pool['available']); self.assertAlmostEqual(pool['g_min_s'],1.5e-5)
        self.assertAlmostEqual(pool['g_max_s'],2e-5)

    def test_publish_immutable_and_hash_csv_round_trip(self):
        r=self.result(); p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        before=copy.deepcopy(p)
        published=publish_profile(p['manifest'],p['states'],'Researcher','Adopt raw positive states')
        self.assertEqual(p,before); self.assertEqual(published['status'],'published')
        self.assertNotEqual(published['profile_hash'],p['manifest']['profile_hash'])
        validate_profile(published,p['states'],published_required=True)
        self.assertEqual(parse_states_csv(states_csv(p['states'])),p['states'])
        tampered=copy.deepcopy(p['states']); tampered[0]['conductance_s']*=2
        with self.assertRaises(ValueError): validate_profile(published,tampered)
        with self.assertRaises(ValueError): publish_profile(published,p['states'],'X','edit immutable')

    def test_invalid_selection_and_mixed_conditions_rejected(self):
        r=self.result()
        with self.assertRaises(ValueError): build_profile('A2',r,[s['state_id'] for s in r['states']])
        with self.assertRaises(ValueError): build_profile('A1',r,['missing'])
        p=build_profile('A1',r,[r['states'][0]['state_id']])
        with self.assertRaises(ValueError): publish_profile(p['manifest'],p['states'],'Reviewer','Only one state')
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        with self.assertRaises(ValueError): publish_profile(p['manifest'],p['states'],'','')





class MeasurementEdgeTests(unittest.TestCase):
    def test_same_file_two_mapped_physical_device_columns(self):
        rows=[{'v':-1,'i1':1e-6,'i2':3e-6},{'v':1,'i1':1e-6,'i2':3e-6}]
        base=dataset([(-1,1e-6),(1,1e-6)],'d2d',file_id='shared',sha256='c'*64,branch='erase',sweep_amplitude_v=1)
        base['rows']=rows
        first=copy.deepcopy(base); first['column_mapping']={'vgs_v':'v','id_a':'i1'}
        second=copy.deepcopy(base); second['device_id']='D2'; second['column_mapping']={'vgs_v':'v','id_a':'i2'}
        self.assertAlmostEqual(analyze('d2d',[first,second],{})['d2d']['cv'],math.sqrt(.5))

    def test_insufficient_samples_final_range_and_positive_ltd(self):
        d=dataset([(6,1e-6,0),(7,0,6),(8,1e-6,0)],direction='ltd')
        r=analyze('pulse_states',[d],{})
        self.assertEqual(r['states'],[])
        self.assertEqual({e['reason'] for e in r['exclusions']},{'insufficient_preceding_read_samples','no_next_transition'})
        r=analyze('pulse_states',[pulse('ltd',values=(1.15e-5,2e-5))],{})
        self.assertAlmostEqual(r['states'][0]['conductance_s'],115e-6)

    def test_d2d_unavailable_is_null_and_no_extrapolation(self):
        ds=[dataset([(1,1e-6),(2,2e-6)],'d2d',branch='erase',sweep_amplitude_v=2,device_id=dev,file_id=dev) for dev in ['D1','D2']]
        d=analyze('d2d',ds,{})['d2d']
        self.assertEqual(d['status'],'unavailable'); self.assertIsNone(d['cv']); self.assertEqual(d['matched_conditions'],0)

    def test_retention_constant_current_and_bias_transfer(self):
        d=dataset([(10,1e-6,2e-6),(100,1e-6,2e-6),(1000,1e-6,2e-6)],'retention',condition_id='A3',source_label='R3(1)',read_vgs_v=.5,header_read_vgs_v=0)
        r=analyze('retention',[d],{})
        self.assertIsNone(r['retention']['program_fit']['r_squared'])
        self.assertEqual(r['retention']['program_fit']['b'],0)
        self.assertEqual(len(r['warnings']),2)
        d['source_label']='R3(2)'
        with self.assertRaises(ValueError): analyze('retention',[d],{})

    def test_branch_reversal_and_signed_maximum(self):
        bad=dataset([(-1,0),(1,2e-6)],'iv',branch='program',sweep_amplitude_v=1)
        with self.assertRaises(ValueError): analyze('iv',[bad],{})
        d=dataset([(-1,-3e-6),(1,-2e-6)],'iv',branch='erase',sweep_amplitude_v=1)
        r=analyze('iv',[d],{})
        self.assertEqual(r['tables']['vth'][0]['max_id_a'],-2e-6)

    def test_common_closed_overlap_uses_actual_candidates(self):
        r=analyze('pulse_states',[pulse(values=(1e-6,3e-6,5e-6)),pulse('ltd',(2e-6,4e-6),file_id='f2')],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        common=p['manifest']['pools']['common']
        self.assertEqual(len(common['state_ids']),3)
        self.assertAlmostEqual(common['common_lo_s'],2e-5)
        self.assertAlmostEqual(common['common_hi_s'],4e-5)
        self.assertEqual(len(p['states']),5)

    def test_disjoint_common_does_not_block_baseline_publish(self):
        r=analyze('pulse_states',[pulse(values=(1e-6,2e-6)),pulse('ltd',(3e-6,4e-6),file_id='f2')],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        published=publish_profile(p['manifest'],p['states'],'R','Keep observed states')
        self.assertFalse(published['pools']['common']['available'])
        self.assertEqual(published['d2d']['status'],'unavailable')

    def test_one_file_can_contain_explicit_ltp_ltd_row_sections(self):
        a=pulse(file_id='both',sha256='c'*64)
        b=pulse('ltd',file_id='both',sha256='c'*64)
        b['source_rows']=[n+100 for n in b['source_rows']]
        r=analyze('pulse_states',[a,b],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        validate_profile(p['manifest'],p['states'])

    def test_draft_hash_cannot_legitimize_malformed_extraction(self):
        from ctfm.profiles import compute_profile_hash
        r=analyze('pulse_states',[pulse()],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        p['manifest']['extraction']['read_tolerance_v']=-1
        p['manifest']['profile_hash']=compute_profile_hash(p['manifest'])
        with self.assertRaises(ValueError): validate_profile(p['manifest'],p['states'])


class ProfileRevisionTests(unittest.TestCase):
    def test_new_revision_keeps_provenance_and_resets_review(self):
        from ctfm.profiles import revise_profile
        r=analyze('pulse_states',[pulse()],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        published=publish_profile(p['manifest'],p['states'],'Reviewer','Positive raw states')
        before=copy.deepcopy(published)
        revision=revise_profile(published,p['states'],display_name='Updated')
        self.assertEqual(revision['manifest']['revision'],2)
        self.assertEqual(revision['manifest']['status'],'draft')
        self.assertIsNone(revision['manifest']['published_at'])
        self.assertIsNone(revision['manifest']['review']['reviewer'])
        self.assertEqual(revision['manifest']['sources'],published['sources'])
        self.assertEqual(published,before)
        self.assertNotEqual(revision['manifest']['profile_hash'],published['profile_hash'])
        with self.assertRaises(ValueError): revise_profile(published,p['states'],revision=1)

class ProfileValidationTests(unittest.TestCase):
    def test_csv_canonical_numbers_are_stable_for_integer_inputs(self):
        r=analyze('pulse_states',[pulse()],{})
        states=copy.deepcopy(r['states']); states[0]['time_s']=6
        encoded=states_csv(states)
        self.assertEqual(states_csv(parse_states_csv(encoded)),encoded)

    def test_schema_exposes_d2d_retention_and_extraction_fields(self):
        from ctfm.profiles import ProfileManifest
        schema=ProfileManifest.model_json_schema()
        for name in ('D2D','Retention','Extraction'):
            self.assertIn(name,schema['$defs'])

    def test_unavailable_retention_cannot_contain_fabricated_fit(self):
        from ctfm.profiles import compute_profile_hash
        r=analyze('pulse_states',[pulse()],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        p['manifest']['retention']['program_fit']={'a':1,'b':0,'n':10,'rmse':0,'r_squared':None,'time_min_s':10,'time_max_s':100}
        p['manifest']['profile_hash']=compute_profile_hash(p['manifest'])
        with self.assertRaises(ValueError): validate_profile(p['manifest'],p['states'])




class ProfileImportTests(unittest.TestCase):
    def test_import_origin_remains_in_canonical_manifest(self):
        from ctfm.profiles import compute_profile_hash
        r=analyze('pulse_states',[pulse()],{})
        p=build_profile('A1',r,[s['state_id'] for s in r['states']])
        p['manifest']['extraction']['import_origin']={'profile_id':p['manifest']['profile_id'],'revision':1,'profile_hash':p['manifest']['profile_hash'],'status':'draft'}
        p['manifest']['profile_hash']=compute_profile_hash(p['manifest'])
        validate_profile(p['manifest'],p['states'])

    def test_missing_measurement_and_string_numeric_rejected_as_valueerror(self):
        from ctfm.profiles import compute_profile_hash
        r=analyze('pulse_states',[pulse()],{})
        for measurement in ({}, {'vds_v':'0.1','read_vgs_v':0,'pulse_width_s':.001,'interval_s':.001,'applied_pulse_count':512,'saturation_verified':False}):
            p=build_profile('A1',r,[s['state_id'] for s in r['states']])
            p['manifest']['measurement']=measurement
            p['manifest']['profile_hash']=compute_profile_hash(p['manifest'])
            with self.assertRaises(ValueError): validate_profile(p['manifest'],p['states'])

if __name__=='__main__': unittest.main()

