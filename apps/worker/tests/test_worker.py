"""Worker integration: a real subprocess must produce traceable measurement artifacts."""
from pathlib import Path
from ctfm_api.storage import Store, sha256
from ctfm_worker.runner import run_once


def test_experiment_summary_accounts_for_the_reprogram_multiplier(tmp_path, monkeypatch):
    """execute.py recomputes summary.requested/skipped independently of
    run_experiment's own (correct) total -- and that duplicate formula did not
    multiply by n_reprogram, so a C2C request with n_reprogram>1 silently got
    requested=1 and skipped=-1 through this exact path (only visible through
    the real worker, never through run_experiment() called directly -- see
    local_report/04_REPORT_c2c-backend.md for how this was actually found)."""
    import hashlib
    import json
    from unittest.mock import patch
    from ctfm.measurement import PARSER_VERSION, DEFAULTS
    from ctfm.profiles import build_profile, publish_profile
    from ctfm.simulation.torch_runner import create_model
    from ctfm_worker.execute import execute

    monkeypatch.setenv("CTFM_STORAGE_ROOT", str(tmp_path))
    store = Store(tmp_path)
    sha = "a" * 64
    source = dict(file_id="synthetic-pulse", sha256=sha, filename="synthetic.csv", sheet=None,
                 device_id="fixture-device", condition_id="SYNTHETIC",
                 columns={"time_s": "t", "vgs_v": "v", "id_a": "i"},
                 units={"time_s": "s", "vgs_v": "V", "id_a": "A"}, read_vgs_v=0, vds_v=.1,
                 direction="ltp", source_rows=list(range(1, 12)))
    states = []
    for i, g in enumerate([1e-5, 2e-5, 4e-5, 5e-5]):
        row = i + 3
        sid = hashlib.sha256(json.dumps([sha, None, row, PARSER_VERSION], separators=(",", ":")).encode()).hexdigest()
        states.append(dict(state_id=sid, source_id="synthetic-pulse", source_row=row, transition_row=row + 2,
                           time_s=6. + i, direction="ltp", pulse_step=None, extraction_index=i + 1,
                           id_a=g * .1, vgs_v=0., conductance_s=g, selected=True, exclusion_reason=None))
    analysis = dict(kind="pulse_states", condition_id="SYNTHETIC", states=states, provenance=[source], settings=dict(DEFAULTS))
    d2d = dict(kind="d2d", condition_id="SYNTHETIC",
              d2d=dict(status="available", cv=.1, source_kind="iv_proxy", physical_device_count=2,
                      matched_conditions=1, distribution="assumed_lognormal", analysis_id=None,
                      assumption_ids=["d2d_lognormal"]))
    fit = dict(a=3e-6, b=-.5e-6, rmse=0., r_squared=1., n=3, time_min_s=10., time_max_s=100.)
    retention = dict(kind="retention", condition_id="SYNTHETIC",
                     retention=dict(status="available", program_fit=fit, erase_fit=fit,
                                   read_vgs_v=0., vds_v=.1, source_label="synthetic fixture"))
    built = build_profile("SYNTHETIC", analysis, [s["state_id"] for s in states], d2d, retention, display_name="SYNTHETIC ONLY")
    built["manifest"] = publish_profile(built["manifest"], built["states"], "worker test",
                                        "Synthetic numerical validation only; no device measurement.")
    store.save_profile(built["manifest"], built["states"])

    request = dict(schema_version="1.3.0",
                  profile_refs=[dict(id=built["manifest"]["profile_id"], revision=1,
                                     c2c=dict(cv_percent=5, source="manual_assumption"))],
                  model_id="mnist_mlp_v1", checkpoint_id=None, pools=["combined"], mappings=["fixed_reference"],
                  effects=dict(d2d=False, retention=False, adc=False, c2c=True),
                  arrays=1, n_reprogram=2, years=[0], seed=20260917,
                  hardware=dict(tile_size=64, adc_bits=None, adc_order=None, range_policy=None, preset_id=None),
                  engines=dict(accuracy="torch_reference", ppa="off"))
    item, job = store.enqueue("experiment", request)
    claimed = store.claim()
    assert claimed["id"] == job["id"]
    import numpy as np
    train = np.zeros((60000, 784), dtype=np.uint8); test = np.zeros((10000, 784), dtype=np.uint8)
    data = (train, np.zeros(60000, dtype=np.uint8), test, np.zeros(10000, dtype=np.uint8), [{"synthetic": True}])
    with patch("ctfm.simulation.load_mnist", return_value=data), patch("ctfm.simulation.train_model", return_value=(create_model(), [])), \
         patch("ctfm.adapters._neurosim_capability", side_effect=AssertionError("NeuroSim capability probed while off")), \
         patch("ctfm.adapters.neurosim.ppa_result", side_effect=AssertionError("PPA evaluation called while off")), \
         patch("ctfm.adapters.neurosim.build_engine_inputs", side_effect=AssertionError("NeuroSim inputs built while off")):
        execute(job["id"])
    # execute() writes worker-result.json but does not itself call store.finish
    # (runner.run_once does that after the real subprocess exits); read the
    # file directly, exactly what execute() actually produced.
    result = json.loads((store.job_dir(job["id"]) / "worker-result.json").read_text(encoding="utf-8"))
    summary = result["summary"]
    # 1 profile * 1 pool * 1 mapping * 1 array * 2 reprogram * 1 year = 2.
    assert summary["requested"] == 2, summary
    assert summary["completed"] == 2, summary
    assert summary["skipped"] == 0, summary
    assert result["effective_config"]["input_encoding"]["bits"] == 8
    assert result["resolved_config"]["hardware"]["adc_order"] is None
    assert result["ppa"]["status"] == "not_evaluated"
    assert result["ppa"]["area_m2"] is None
    assert result["ppa"]["energy_j_per_inference"] is None
    assert result["ppa"]["latency_s_per_inference"] is None


def test_worker_rejects_queued_ppa_request_without_api(tmp_path, monkeypatch):
    import json
    import pytest
    from ctfm_contracts.check_experiment_contract import ContractError
    from ctfm_worker.execute import execute

    monkeypatch.setenv("CTFM_STORAGE_ROOT", str(tmp_path))
    store = Store(tmp_path)
    fixture = Path(__file__).resolve().parents[3] / "packages/contracts/fixtures/experiment-effects.request.json"
    request = json.loads(fixture.read_text(encoding="utf-8"))
    request["schema_version"] = "1.4.0"
    request["hardware"].update(tile_size=64, adc_bits=5, adc_order="adc_then_subtract")
    request["engines"]["ppa"] = "assumed_proxy"
    _, job = store.enqueue("experiment", request)
    store.claim()
    with pytest.raises(ContractError, match="PPA") as error:
        execute(job["id"])
    assert error.value.field == "engines.ppa"


def test_analysis_job_executes_in_subprocess_and_exports(tmp_path):
    store=Store(tmp_path)
    data=b"time,id,gate\n5,0.000001,0\n6,0.000001,0\n6.1,0.000001,0\n6.2,0.000001,-10\n6.3,0.000001,0\n7,0.000002,0\n7.1,0.000002,0\n7.2,0.000002,-10\n7.3,0.000002,0\n"
    import uuid
    fid=str(uuid.uuid4());relative="uploads/"+fid+".csv"
    store.managed_path(relative).write_bytes(data)
    store.put_entity("file",fid,dict(file_id=fid,name="synthetic.csv",sha256=sha256(data),relative_path=relative))
    request=dict(kind="pulse_states",inputs=[dict(file_id=fid,column_mapping=dict(time_s="time",id_a="id",vgs_v="gate"),units=dict(time_s="s",id_a="A",vgs_v="V"),device_id="synthetic-only",condition_id="A1",direction="ltp",read_vgs_v=0,vds_v=.1)],settings={})
    item,job=store.enqueue("analysis",request)
    assert run_once(store)
    finished=store.get_job(job["id"])
    assert finished["state"]=="succeeded",finished
    result=store.get_entity("analysis",item["id"])
    assert len(result["states"])==2
    assert abs(result["states"][0]["conductance_s"]-1e-5)<1e-15
    assert {"csv","xlsx","json","png"} <= {a["kind"] for a in result["artifacts"]}
    for artifact in result["artifacts"]:
        assert store.artifact_path(artifact["id"]).is_file()
    assert run_once(store) is False

def test_cancel_stops_only_owned_running_subprocess(tmp_path, monkeypatch):
    import subprocess
    import sys
    import threading
    import time
    import ctfm_worker.runner as runner
    store=Store(tmp_path)
    item,job=store.enqueue("analysis",{"synthetic_cancel_fixture":True})
    original=subprocess.Popen;owned=[]
    def slow_child(command,**kwargs):
        process=original([sys.executable,"-c","import time;time.sleep(30)"],**kwargs)
        owned.append(process);return process
    monkeypatch.setattr(runner.subprocess,"Popen",slow_child)
    # taskkill must use the original Popen internally rather than this fixture.
    monkeypatch.setattr(runner,"terminate_owned_process",lambda process: (process.terminate(),process.wait(timeout=5)))
    thread=threading.Thread(target=run_once,args=(store,));thread.start()
    deadline=time.monotonic()+10
    while not owned and time.monotonic()<deadline:time.sleep(.05)
    assert owned
    store.cancel(job["id"]);thread.join(timeout=10)
    assert not thread.is_alive()
    assert owned[0].poll() is not None
    assert store.get_job(job["id"])["state"]=="cancelled"
    assert store.get_entity("analysis",item["id"])["status"]=="cancelled"

def test_second_worker_cannot_acquire_same_storage(tmp_path):
    import pytest
    from ctfm_worker.runner import worker_lock
    store=Store(tmp_path)
    with worker_lock(store):
        with pytest.raises(RuntimeError,match="Another worker"):
            with worker_lock(store):pass

def test_run_once_survives_a_locked_claim_and_polls_again(tmp_path,monkeypatch):
    """A transient 'database is locked' while claiming the next job (e.g. a slow /comparisons/run
    request holding the writer lock) must not crash the worker process; run_once should report
    no work done this cycle so the caller's normal poll loop just tries again."""
    import sqlite3
    store=Store(tmp_path)
    def always_locked():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store,"claim",always_locked)
    assert run_once(store) is False
    # the worker is still usable afterwards -- this was not a fatal condition
    monkeypatch.undo()
    item,job=store.enqueue("analysis",{"kind":"iv"})
    assert store.claim()["id"]==job["id"]

def test_run_once_reraises_the_original_failure_even_if_finish_is_also_locked(tmp_path,monkeypatch):
    """If the job itself fails for a real reason while the DB happens to also be locked when
    run_once tries to record that failure, the original failure must still surface (never hidden
    behind the incidental lock), and run_once itself must not raise a second, different error."""
    import pytest
    import sqlite3
    import ctfm_worker.runner as runner
    store=Store(tmp_path)
    item,job=store.enqueue("analysis",{"kind":"iv"})
    def boom(*args,**kwargs):raise RuntimeError("subprocess could not start")
    monkeypatch.setattr(runner.subprocess,"Popen",boom)
    def locked_finish(*args,**kwargs):raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store,"finish",locked_finish)
    with pytest.raises(RuntimeError,match="subprocess could not start"):
        run_once(store)

def test_main_once_survives_a_locked_claim_without_crashing(tmp_path,monkeypatch):
    """The --once entry point (what a supervisor actually runs) must return normally instead of
    exiting with an unhandled exception when the database is transiently locked."""
    import sqlite3,sys
    import ctfm_worker.runner as runner
    store=Store(tmp_path)
    monkeypatch.setattr(runner,"Store",lambda *a,**k:store)
    def boom(s):raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(runner,"run_once",boom)
    monkeypatch.setattr(sys,"argv",["ctfm_worker","--once"])
    runner.main()

def test_spreadsheet_exports_keep_untrusted_strings_as_text(tmp_path):
    from ctfm_worker.exports import export_result
    from openpyxl import load_workbook
    import csv
    export_result({"tables":{"notes":[{"label":"=1+1","value":-2}]}},tmp_path)
    with (tmp_path/"notes.csv").open(encoding="utf-8-sig",newline="") as stream:
        row=list(csv.DictReader(stream))[0]
    assert row["label"]=="'=1+1"
    workbook=load_workbook(tmp_path/"tables.xlsx",data_only=False)
    assert workbook["notes"]["A2"].data_type=="s"
    assert workbook["notes"]["A2"].value=="=1+1"
    workbook.close()

def test_spreadsheet_export_scales_to_measured_table_size(tmp_path):
    # A measured LTP+LTD pair yields 24k raw rows; a per-row max_row scan made this hang for minutes.
    import time
    from ctfm_worker.exports import export_result
    rows=[{"row":i,"label":"=x","value":i*1e-6} for i in range(24000)]
    started=time.monotonic()
    export_result({"tables":{"raw":rows}},tmp_path)
    assert time.monotonic()-started<60


def test_failed_comparison_subprocess_retains_partial_rows_and_checkpoint(tmp_path,monkeypatch):
    import json,subprocess,sys
    from uuid import uuid4
    import ctfm_worker.runner as runner
    from ctfm_api.comparisons import create,write
    from ctfm_api.storage import encode
    store=Store(tmp_path);pid=str(uuid4());cpid=str(uuid4())
    card=dict(card_id=str(uuid4()),display_name='synthetic',profile_ref=dict(id=pid,revision=1),status='queued')
    with store.connection() as db:
        comparison=create(db,dict(common_settings={},cards=[]))
    item,job=store.enqueue('experiment',{})
    item['comparison_id']=comparison['comparison_id'];store.put_entity('experiment',item['id'],item,replace=True)
    comparison.update(lifecycle='running',experiment_id=item['id'],job_id=job['id'],cards=[card])
    with store.connection() as db:write(db,comparison)
    row=dict(profile_id=pid,profile_revision=1,candidate_id='candidate-1',kind='ALL',status='succeeded',accuracy=.75)
    partial=dict(checkpoint_id=cpid,checkpoint_filename='checkpoint.pt',runs=[row])
    script="from pathlib import Path;import sys;p=Path("+repr(str(store.job_dir(job['id'])))+");(p/'checkpoint.pt').write_bytes(b'completed training');(p/'comparison-partial.json').write_text("+repr(json.dumps(partial))+");sys.exit(1)"
    original=subprocess.Popen
    monkeypatch.setattr(runner.subprocess,'Popen',lambda command,**kwargs:original([sys.executable,'-c',script],**kwargs))
    assert run_once(store)
    result=store.get_entity('comparison',comparison['comparison_id'])
    assert result['lifecycle']=='temporary' and result['outcome']=='partial'
    assert result['cards'][0]['runs']==[row]
    checkpoint=store.get_entity('checkpoint',cpid)
    assert store.managed_path(checkpoint['relative_path']).read_bytes()==b'completed training'
    assert store.get_job(job['id'])['state']=='failed'
