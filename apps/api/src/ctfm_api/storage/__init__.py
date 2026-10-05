"""Managed SQLite metadata, immutable artifact paths and one-worker queue."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import UUID, uuid4


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def default_root():
    candidate = Path(__file__).resolve().parents[5]
    base = candidate if (candidate / "docs/spec").is_dir() else Path.cwd()
    return Path(os.environ.get("CTFM_STORAGE_ROOT", base / "runtime")).resolve()


class Store:
    def __init__(self, root=None, *, db_timeout=30):
        self.root = Path(root or default_root()).resolve()
        self.db_timeout = db_timeout
        for directory in ("uploads", "artifacts", "db", "cache"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "db/ctfm.sqlite3"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entities (
                    kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL, manifest TEXT NOT NULL, states TEXT NOT NULL,
                    PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                    state TEXT NOT NULL, stage TEXT, progress REAL NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, error TEXT, pid INTEGER);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=self.db_timeout)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _retry_locked(self, attempt, *, attempts=3, base_delay=0.2):
        """Retry a whole connection/transaction a bounded number of times when SQLite reports the
        database as busy/locked past its own internal `timeout`. Each attempt opens a fresh
        connection (see `connection()`), and a failed attempt never partially commits -- sqlite3
        rolls the transaction back when the `with db:` block exits on exception -- so retrying is
        safe and cannot duplicate a write."""
        for remaining in range(attempts - 1, -1, -1):
            try:
                return attempt()
            except sqlite3.OperationalError as exc:
                if remaining == 0 or "locked" not in str(exc).lower():
                    raise
                time.sleep(base_delay * (2 ** (attempts - 1 - remaining)))

    def managed_path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Path is outside managed storage")
        return path

    def job_dir(self, job_id):
        return self.managed_path("artifacts/" + str(UUID(str(job_id))))

    def put_entity(self, kind, identifier, data, *, replace=False):
        def attempt():
            with self.connection() as db:
                query = "INSERT OR REPLACE" if replace else "INSERT"
                db.execute(f"{query} INTO entities(kind,id,data,created_at) VALUES(?,?,?,?)",
                           (kind, identifier, encode(data), data.get("created_at", now())))
        self._retry_locked(attempt)

    def get_entity(self, kind, identifier):
        with self.connection() as db:
            row = db.execute("SELECT data FROM entities WHERE kind=? AND id=?", (kind, identifier)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return json.loads(row["data"])

    def list_entities(self, kind):
        with self.connection() as db:
            rows = db.execute("SELECT data FROM entities WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def enqueue(self, kind, request):
        if kind not in ("analysis", "experiment"):
            raise ValueError("Unsupported job kind")
        identifier, job_id, timestamp = str(uuid4()), str(uuid4()), now()
        item = {"id": identifier, f"{kind}_id": identifier, "job_id": job_id,
                "status": "queued", "request": request, "created_at": timestamp, "artifacts": []}
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Bound pending work even when callers split comparison requests.
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            if count >= 100:
                raise ValueError("The queue is full (100 pending jobs)")
            db.execute("INSERT INTO entities(kind,id,data,created_at) VALUES(?,?,?,?)",
                       (kind, identifier, encode(item), timestamp))
            db.execute("INSERT INTO jobs(id,kind,entity_id,state,stage,created_at) VALUES(?,?,?,'queued','queued',?)",
                       (job_id, kind, identifier, timestamp))
        return item, self.get_job(job_id)

    def get_job(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        job = dict(row)
        job["cancel_requested"] = bool(job["cancel_requested"])
        job["error"] = json.loads(job["error"]) if job["error"] else None
        return job

    def list_jobs(self):
        with self.connection() as db:
            rows = db.execute("SELECT id FROM jobs ORDER BY created_at DESC").fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def claim(self):
        def attempt():
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM jobs WHERE state='queued' AND cancel_requested=0 ORDER BY created_at,id LIMIT 1").fetchone()
                if row is None:
                    return None
                db.execute("UPDATE jobs SET state='running',started_at=?,stage='parsing' WHERE id=?", (now(), row["id"]))
                item = json.loads(db.execute("SELECT data FROM entities WHERE kind=? AND id=?", (row["kind"], row["entity_id"])).fetchone()[0])
                item["status"] = "running"
                db.execute("UPDATE entities SET data=? WHERE kind=? AND id=?", (encode(item), row["kind"], row["entity_id"]))
                return row["id"]
        identifier = self._retry_locked(attempt)
        return self.get_job(identifier) if identifier is not None else None

    def set_pid(self, job_id, pid):
        def attempt():
            with self.connection() as db:
                db.execute("UPDATE jobs SET pid=? WHERE id=? AND state='running'", (pid, job_id))
        self._retry_locked(attempt)

    def progress(self, job_id, stage, completed, total):
        if total < 0 or completed < 0 or completed > total:
            raise ValueError("Invalid progress")
        def attempt():
            with self.connection() as db:
                db.execute("UPDATE jobs SET stage=?,completed=?,total=?,progress=? WHERE id=? AND state='running'",
                           (stage, completed, total, completed / total if total else 0, job_id))
        self._retry_locked(attempt)

    def finish(self, job_id, *, state, result=None, error=None):
        if state not in ("succeeded", "failed", "cancelled"):
            raise ValueError("Invalid terminal state")
        def attempt():
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if job is None:
                    raise KeyError(job_id)
                if job["state"] not in ("queued", "running"):
                    return False
                job_state = state
                if job["cancel_requested"]:
                    job_state = "cancelled"
                db.execute("UPDATE jobs SET state=?,stage=?,finished_at=?,error=?,pid=NULL,progress=? WHERE id=?",
                           (job_state, job_state, now(), encode(error) if error else None, 1 if job_state == "succeeded" else job["progress"], job_id))
                item = json.loads(db.execute("SELECT data FROM entities WHERE kind=? AND id=?", (job["kind"], job["entity_id"])).fetchone()[0])
                item_result = result
                if job["cancel_requested"] and not item.get("comparison_id"):
                    item_result = None
                if item.get("comparison_id") and not item_result:
                    partial=self.job_dir(job_id)/"comparison-partial.json"
                    if partial.is_file():
                        try: item_result=json.loads(partial.read_text(encoding="utf-8"))
                        except (OSError,ValueError): pass
                if item_result:
                    item.update(item_result)
                item["status"] = item_result.get("status", job_state) if item_result and job_state == "succeeded" else job_state
                item["finished_at"] = now()
                if error:
                    item["error"] = error
                db.execute("UPDATE entities SET data=? WHERE kind=? AND id=?", (encode(item), job["kind"], job["entity_id"]))
                if item.get("comparison_id"):
                    from ctfm_api.comparisons import reconcile
                    reconcile(db, item)
                return True
        return self._retry_locked(attempt)

    def cancel(self, job_id):
        def attempt():
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                job = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
                if job is None:
                    raise KeyError(job_id)
                if job["state"] in ("queued", "running"):
                    db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
                return job["state"]
        state = self._retry_locked(attempt)
        if state == "queued":
            self.finish(job_id, state="cancelled")
        return self.get_job(job_id)

    def _recover_comparison_outputs(self, job_id):
        """Register completed partial outputs before recovery exposes terminal references.

        A second supervisor crash can happen between registration and finish; reuse
        matching entities rather than replacing shared checkpoints or duplicating artifacts.
        """
        output=self.job_dir(job_id)
        if output != self.root/'artifacts'/str(UUID(job_id)):
            raise ValueError("Recovery requires the exact owned job directory")
        partial=output/"comparison-partial.json"
        try:
            result=json.loads(partial.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            return None
        if not isinstance(result,dict): return None
        checkpoint_path=None
        if result.get("checkpoint_filename"):
            try:
                path=(output/result["checkpoint_filename"]).resolve()
                pin=result.get("provenance",{}).get("checkpoint",{})
                identifier=str(UUID(result["checkpoint_id"]))
                if not path.is_relative_to(output) or not path.is_file():
                    raise ValueError("Recovered checkpoint path is unavailable")
                digest=sha256(path.read_bytes())
                if digest!=pin.get("sha256") or pin.get("checkpoint_id")!=identifier or pin.get("model_id")!="mnist_mlp_v1":
                    raise ValueError("Recovered checkpoint does not match its completed snapshot pin")
                checkpoint=dict(checkpoint_id=identifier,relative_path=path.relative_to(self.root).as_posix(),sha256=digest,model_id="mnist_mlp_v1")
                try: existing=self.get_entity("checkpoint",identifier)
                except KeyError: self.put_entity("checkpoint",identifier,checkpoint)
                else:
                    if any(existing.get(key)!=value for key,value in checkpoint.items()):
                        raise ValueError("Recovered checkpoint conflicts with an existing immutable checkpoint")
                checkpoint_path=path
            except (OSError,ValueError,KeyError,TypeError) as exc:
                result.pop("checkpoint_id",None);result.pop("checkpoint_filename",None)
                result["checkpoint_recovery_error"]=str(exc)
        existing_artifacts={a["relative_path"]:a for a in self.list_entities("artifact")}
        artifacts=[]
        for path in sorted(output.rglob("*")):
            path=path.resolve()
            if not path.is_relative_to(output) or not path.is_file() or path.name.startswith("worker-") or path.suffix==".tmp": continue
            if path.suffix==".pt" and path!=checkpoint_path: continue
            relative=path.relative_to(self.root).as_posix()
            existing=existing_artifacts.get(relative)
            if existing:
                if existing["sha256"]!=sha256(path.read_bytes()): continue
                artifacts.append({k:v for k,v in existing.items() if k!="relative_path"})
            else:
                artifacts.append(self.register_artifact(path,path.suffix.lstrip(".") or "file"))
        result["artifacts"]=artifacts
        return result

    def recover_interrupted(self):
        with self.connection() as db:
            rows = db.execute("SELECT id FROM jobs WHERE state='running'").fetchall()
        recovered = 0
        for row in rows:
            job_id = row["id"]
            # A pending-finish.json means a prior worker already computed this job's real outcome
            # and only failed to commit it (a lock, not a crash mid-calculation). That outcome is
            # authoritative and must win: leave the job 'running' so ctfm_worker.runner's own
            # _flush_pending_finishes -- called before this method and on every poll iteration --
            # commits it, instead of this method overwriting a success as "interrupted"/failed.
            if (self.job_dir(job_id) / "pending-finish.json").is_file():
                continue
            job=self.get_job(job_id)
            item=self.get_entity(job["kind"],job["entity_id"])
            result=self._recover_comparison_outputs(job_id) if item.get("comparison_id") else None
            self.finish(job_id, state="failed", result=result, error={"code": "interrupted", "message": "Worker stopped before completing this job."})
            recovered += 1
        return recovered

    def save_profile(self, manifest, states, *, replace_draft=False):
        identifier, revision = str(UUID(manifest["profile_id"])), manifest["revision"]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT status FROM profiles WHERE id=? AND revision=?", (identifier, revision)).fetchone()
            if existing:
                if existing["status"] == "published":
                    raise ValueError("Published revisions are immutable")
                if not replace_draft:
                    raise ValueError("Revision already exists")
                db.execute("UPDATE profiles SET status=?,manifest=?,states=? WHERE id=? AND revision=?",
                           (manifest["status"], encode(manifest), encode(states), identifier, revision))
            else:
                db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)", (identifier, revision, manifest["status"], encode(manifest), encode(states)))

    def create_profile_revision(self, identifier, base_revision, build):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT manifest,states FROM profiles WHERE id=? AND revision=?",(identifier,base_revision)).fetchone()
            if row is None: raise KeyError(identifier)
            revision=db.execute("SELECT MAX(revision) FROM profiles WHERE id=?",(identifier,)).fetchone()[0]+1
            result=build(json.loads(row['manifest']),json.loads(row['states']),revision)
            db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)",(identifier,revision,'draft',encode(result['manifest']),encode(result['states'])))
            return result

    def get_profile(self, identifier, revision):
        identifier = str(UUID(str(identifier)))
        with self.connection() as db:
            row = db.execute("SELECT manifest,states FROM profiles WHERE id=? AND revision=?", (identifier, revision)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return {"manifest": json.loads(row["manifest"]), "states": json.loads(row["states"])}

    def list_profiles(self, status=None):
        with self.connection() as db:
            rows = db.execute("SELECT manifest FROM profiles WHERE (? IS NULL OR status=?) ORDER BY id,revision DESC", (status, status)).fetchall()
        return [json.loads(row["manifest"]) for row in rows]

    def next_revision(self, identifier):
        with self.connection() as db:
            maximum = db.execute("SELECT MAX(revision) FROM profiles WHERE id=?", (identifier,)).fetchone()[0]
        return (maximum or 0) + 1

    def register_artifact(self, path, kind):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root / "artifacts") or not path.is_file():
            raise ValueError("Artifact is not a managed file")
        import mimetypes
        identifier = str(uuid4())
        data = path.read_bytes()
        # Only what exports.py deliberately writes under user/ is offered as a download; checkpoints,
        # arrays, diagnostics and any file added later stay internal (kept for reproduction/recovery).
        role = "user" if path.parent.name == "user" else "internal"
        artifact = {"id": identifier, "kind": kind, "role": role, "filename": path.name,
                    "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "sha256": sha256(data), "size_bytes": len(data),
                    "download_url": f"/api/v1/artifacts/{identifier}/download",
                    "relative_path": path.relative_to(self.root).as_posix()}
        self.put_entity("artifact", identifier, artifact)
        return {key: value for key, value in artifact.items() if key != "relative_path"}

    def artifact_path(self, identifier):
        artifact = self.get_entity("artifact", identifier)
        path = self.managed_path(artifact["relative_path"])
        if not path.is_file() or sha256(path.read_bytes()) != artifact["sha256"]:
            raise ValueError("Artifact hash mismatch")
        return path
