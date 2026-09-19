"""A crashed supervisor must not leave an active calculation behind."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

def test_child_stops_when_its_supervisor_exits(tmp_path):
    parent_script=tmp_path/"parent.py"
    marker=tmp_path/"heartbeat"
    child_code="from ctfm_worker.lifecycle import guard_parent; import pathlib,time; guard_parent(); p=pathlib.Path("+repr(str(marker))+");\nfor i in range(100): p.write_text(str(i)); time.sleep(.1)"
    parent_script.write_text("import os,subprocess,sys,time\nenv=os.environ.copy();env['CTFM_PARENT_PID']=str(os.getpid())\np=subprocess.Popen([sys.executable,'-c',"+repr(child_code)+"],env=env,start_new_session=(os.name!='nt'))\ntime.sleep(1.5)\n",encoding="utf-8")
    parent=subprocess.Popen([sys.executable,str(parent_script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdout,stderr=parent.communicate(timeout=15)
    assert parent.returncode==0,stderr
    assert marker.exists(),stderr
    time.sleep(1.5);value=marker.read_text()
    time.sleep(.7)
    assert marker.read_text()==value,"Calculation survived its completed parent"
