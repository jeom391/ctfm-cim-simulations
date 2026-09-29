"""Comparison failure boundaries preserve scientific identities and multiplicities."""
import json
import pytest
import ctfm.simulation as simulation
from ctfm.simulation.torch_runner import create_model
from test_simulation_experiment import configuration, synthetic_profile, synthetic_data

@pytest.fixture
def synthetic_runtime(monkeypatch):
    monkeypatch.setattr(simulation,'load_mnist',lambda *a:synthetic_data())
    monkeypatch.setattr(simulation,'train_model',lambda *a:(create_model(),[]))

@pytest.mark.parametrize('failing_candidate',[1,2])
def test_calibration_failure_isolates_either_profile_and_keeps_peer(tmp_path,monkeypatch,synthetic_runtime,failing_candidate):
    p,q=synthetic_profile(),synthetic_profile()
    cfg=configuration(p,False);cfg['pools']=['combined'];cfg['profile_refs'].append(dict(id=q['manifest']['profile_id'],revision=1))
    cfg['effects']['adc']=True;cfg['hardware'].update(tile_size=64,adc_bits=5,adc_order='adc_then_subtract',range_policy='validation_max_abs')
    calibrate=simulation.calibrate;count=[]
    def injected(*args):
        count.append(1)
        if len(count)==failing_candidate:raise ValueError('synthetic calibration failure')
        return calibrate(*args)
    monkeypatch.setattr(simulation,'calibrate',injected)
    result=simulation.run_experiment(cfg,[p,q],tmp_path,cache_dir=tmp_path/'cache',comparison=True)
    rows=[r for r in result['runs'] if r['kind']=='ALL']
    assert [r['status'] for r in rows]==(['failed','succeeded'] if failing_candidate==1 else ['succeeded','failed'])
    assert result['summary']['requested']==2 and result['summary']['failed']==1 and result['summary']['completed']==1
    assert rows[failing_candidate-1]['accuracy'] is None
    assert rows[2-failing_candidate]['accuracy'] is not None


def test_all_failed_profiles_count_every_array_reprogram_year(tmp_path,synthetic_runtime):
    p,q=synthetic_profile(),synthetic_profile()
    cfg=configuration(p,True);cfg['pools']=['combined'];cfg['profile_refs'].append(dict(id=q['manifest']['profile_id'],revision=1))
    for profile in (p,q):profile['manifest']['profile_hash']='0'*64
    result=simulation.run_experiment(cfg,[p,q],tmp_path,cache_dir=tmp_path/'cache',comparison=True)
    assert {k:result['summary'][k] for k in ('requested','completed','failed','skipped')}==dict(requested=8,completed=0,failed=8,skipped=0)
    assert all(r['accuracy'] is None for r in result['runs'] if r['kind']=='ALL')


def test_cancellation_is_not_swallowed_and_completed_rows_are_durable(tmp_path,synthetic_runtime):
    p,q=synthetic_profile(),synthetic_profile()
    cfg=configuration(p,False);cfg['pools']=['combined'];cfg['profile_refs'].append(dict(id=q['manifest']['profile_id'],revision=1))
    def cancel(stage,completed,total):
        if stage=='inference' and completed==1:raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        simulation.run_experiment(cfg,[p,q],tmp_path,cache_dir=tmp_path/'cache',comparison=True,progress=cancel)
    partial=json.loads((tmp_path/'comparison-partial.json').read_text())
    rows=[r for r in partial['runs'] if r['kind']=='ALL']
    assert len(rows)==1 and rows[0]['profile_id']==p['manifest']['profile_id'] and rows[0]['status']=='succeeded'
    assert (tmp_path/'checkpoint.pt').is_file()


def test_malformed_profile_states_are_isolated_before_mapping(tmp_path,synthetic_runtime):
    p,q=synthetic_profile(),synthetic_profile()
    cfg=configuration(p,False);cfg['pools']=['combined'];cfg['profile_refs'].append(dict(id=q['manifest']['profile_id'],revision=1))
    del p['states'][0]['state_id']
    result=simulation.run_experiment(cfg,[p,q],tmp_path,cache_dir=tmp_path/'cache',comparison=True)
    assert result['summary']['failed']==1 and result['summary']['completed']==1
