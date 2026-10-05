"""Per-source onset must not count the delayed source's pre-write read as a state."""
from ctfm.measurement import analyze


def test_different_file_onsets_keep_each_prewrite_read_excluded():
    datasets=[]
    for direction, onset, sign in [('ltp',1.,-1),('ltd',2.,1)]:
        rows=[{'t':onset+t,'i':1e-6,'v':v*sign} for t,v in [(-.2,0),(-.1,0),(0,10),(.1,10),(.2,0),(.3,0),(.4,10),(.5,10),(.6,0)]]
        datasets.append(dict(file_id=direction, sha256=('a' if direction=='ltp' else 'b')*64, filename=direction+'.csv',
            device_id='measurement-source:'+direction, condition_id='A1', direction=direction, start_time_s=onset,
            vds_v=.1, read_vgs_v=0., column_mapping={'time_s':'t','id_a':'i','vgs_v':'v'},units={'time_s':'s','id_a':'A','vgs_v':'V'},rows=rows,source_rows=list(range(2,11))))
    result=analyze('pulse_states',datasets,{'start_time_s':1.})
    assert len(result['states'])==2
    assert [s['source_row'] for s in result['states']]==[6,6]
    assert [e['reason'] for e in result['exclusions']].count('before_start_time')==2
    assert len(result['tables']['raw'])==18
