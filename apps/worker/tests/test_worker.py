"""Worker integration: a real subprocess must produce traceable measurement artifacts."""
from pathlib import Path
from ctfm_api.storage import Store, sha256
from ctfm_worker.runner import run_once

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
