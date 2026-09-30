"""Durable, singleton queue consumer with owned subprocess cancellation."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from ctfm_api.storage import Store, sha256

def _is_locked(exc):
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()

class _FinishDeferred(Exception):
    """The job's terminal outcome was computed and written to disk, but the database is still
    locked past its retry budget. Not a job failure: a later poll iteration (this run or after a
    restart) flushes the same outcome from disk -- the calculation is never repeated."""

def _finish_or_defer(store, job_id, *, state, result=None, error=None):
    try:
        store.finish(job_id, state=state, result=result, error=error)
    except sqlite3.OperationalError as exc:
        if not _is_locked(exc):raise
        pending=store.job_dir(job_id)/"pending-finish.json"
        pending.write_text(json.dumps(dict(state=state,result=result,error=error),ensure_ascii=False),encoding="utf-8")
        print(f"worker: database busy recording job {job_id}'s outcome ({state}); deferred to {pending.name}, will retry next poll",file=sys.stderr,flush=True)
        raise _FinishDeferred(job_id) from exc

def _flush_pending_finishes(store):
    """Retry any outcome deferred by _finish_or_defer once the lock has had a chance to clear.
    Called on every poll iteration (and once at startup before recover_interrupted), so a job
    stuck 'running' only because its finish() write was locked gets closed out as soon as
    possible -- never by recomputing it, and never by discarding a successful result."""
    root=store.root/"artifacts"
    if not root.is_dir():return
    for pending in sorted(root.glob("*/pending-finish.json")):
        job_id=pending.parent.name
        try:
            payload=json.loads(pending.read_text(encoding="utf-8"))
            job=store.get_job(job_id)
        except (OSError,ValueError,KeyError):
            pending.unlink(missing_ok=True);continue
        try:
            comparison_id=store.get_entity(job["kind"],job["entity_id"]).get("comparison_id")
        except KeyError:
            comparison_id=None
        try:
            store.finish(job_id,state=payload["state"],result=payload.get("result"),error=payload.get("error"))
        except sqlite3.OperationalError as exc:
            if not _is_locked(exc):raise
            continue
        pending.unlink(missing_ok=True)
        if comparison_id:
            from ctfm_api.comparisons import cleanup
            cleanup(store,comparison_id)

@contextmanager
def worker_lock(store):
    path=store.root/"db/worker.lock"
    with path.open("a+b") as stream:
        if stream.tell()==0:stream.write(b"0");stream.flush()
        stream.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another worker already owns this storage directory") from exc
        try:yield
        finally:
            stream.seek(0)
            if os.name=="nt":msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

def terminate_owned_process(process):
    if process.poll() is not None:return
    if os.name=="nt":
        subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:return
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name!="nt":
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        else:process.kill()
        process.wait(timeout=5)

def run_once(store):
    _flush_pending_finishes(store)
    try:
        job=store.claim()
    except sqlite3.OperationalError as exc:
        if not _is_locked(exc):raise
        print(f"worker: database busy while claiming the next job; will retry next poll: {exc}",file=sys.stderr,flush=True)
        return False
    if job is None:return False
    output=store.job_dir(job["id"]);process=None
    comparison_id=store.get_entity(job["kind"],job["entity_id"]).get("comparison_id")
    try:
        output.mkdir(parents=True,exist_ok=False)
        env=os.environ.copy();env["CTFM_STORAGE_ROOT"]=str(store.root);env["PYTHONUNBUFFERED"]="1";env["PYTHONUTF8"]="1";env["CTFM_PARENT_PID"]=str(os.getpid())
        options={"creationflags":subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=="nt" else {"start_new_session":True}
        with (output/"worker.log").open("wb") as log:
            process=subprocess.Popen([sys.executable,"-m","ctfm_worker.execute",job["id"]],stdout=log,stderr=subprocess.STDOUT,env=env,**options)
            store.set_pid(job["id"],process.pid)
            while process.poll() is None:
                if store.get_job(job["id"])["cancel_requested"]:
                    terminate_owned_process(process);break
                time.sleep(.2)
        cancelled=store.get_job(job["id"])["cancel_requested"]
        if cancelled and not comparison_id:
            _finish_or_defer(store,job["id"],state="cancelled");return True
        result_path=output/"worker-result.json"
        result=json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        if not result and comparison_id:
            partial=output/"comparison-partial.json"
            if partial.is_file(): result=json.loads(partial.read_text(encoding="utf-8"))
        artifacts=[]
        for path in sorted(output.rglob("*")):
            if not path.is_file() or path.name.startswith("worker-"):continue
            artifacts.append(store.register_artifact(path,path.suffix.lstrip(".") or "file"))
        result["artifacts"]=artifacts
        filename=result.get("checkpoint_filename")
        if filename:
            path=(output/filename).resolve()
            if not path.is_relative_to(output) or not path.is_file():raise ValueError("Invalid generated checkpoint path")
            store.put_entity("checkpoint",result["checkpoint_id"],dict(checkpoint_id=result["checkpoint_id"],relative_path=path.relative_to(store.root).as_posix(),sha256=sha256(path.read_bytes()),model_id="mnist_mlp_v1"))
        if cancelled:
            _finish_or_defer(store,job["id"],state="cancelled",result=result)
        elif process.returncode==0 and result_path.is_file():
            _finish_or_defer(store,job["id"],state="succeeded",result=result)
        else:
            error_path=output/"worker-error.json"
            error=json.loads(error_path.read_text(encoding="utf-8")) if error_path.is_file() else {"code":"worker_failed","message":"Calculation subprocess exited without a result."}
            _finish_or_defer(store,job["id"],state="failed",result=result,error=error)
    except _FinishDeferred:
        # The outcome (including a success) is safely on disk; a later poll will commit it.
        return True
    except BaseException:
        if process is not None:terminate_owned_process(process)
        try:
            _finish_or_defer(store,job["id"],state="failed",error={"code":"worker_failed","message":"Worker could not complete the job."})
        except _FinishDeferred:
            pass
        raise
    if comparison_id:
        from ctfm_api.comparisons import cleanup
        cleanup(store,comparison_id)
    return True

def main():
    import argparse
    parser=argparse.ArgumentParser(description="Run the single CTFM analysis/experiment worker")
    parser.add_argument("--once",action="store_true",help="Process at most one queued job and exit")
    parser.add_argument("--poll-seconds",type=float,default=1)
    args=parser.parse_args()
    if args.poll_seconds<.1:parser.error("poll interval must be at least 0.1 seconds")
    store=Store()
    with worker_lock(store):
        _flush_pending_finishes(store)
        interrupted=store.recover_interrupted()
        if interrupted:print(f"Recorded {interrupted} interrupted jobs.",flush=True)
        while True:
            try:
                worked=run_once(store)
            except sqlite3.OperationalError as exc:
                if not _is_locked(exc):raise
                print(f"worker: database busy; continuing after backoff: {exc}",file=sys.stderr,flush=True)
                worked=False
            if args.once:return
            if not worked:time.sleep(args.poll_seconds)

if __name__=="__main__":main()
