from pathlib import Path
import pytest
from ctfm_api.storage import Store


def test_atomic_claim_cancel_and_completion(tmp_path):
    store = Store(tmp_path)
    item, job = store.enqueue("analysis", {"kind": "iv", "inputs": [], "settings": {}})
    assert store.get_job(job["id"])["state"] == "queued"
    claimed = store.claim()
    assert claimed["id"] == job["id"]
    assert store.claim() is None
    store.progress(job["id"], "parsing", 1, 4)
    assert store.get_job(job["id"])["progress"] == .25
    store.cancel(job["id"])
    assert store.get_job(job["id"])["cancel_requested"]
    store.finish(job["id"], state="cancelled")
    assert store.get_entity("analysis", item["id"])["status"] == "cancelled"
    assert not store.finish(job["id"], result={"accuracy": 1}, state="succeeded")
    assert store.get_job(job["id"])["state"] == "cancelled"


def test_queued_cancel_never_runs(tmp_path):
    store = Store(tmp_path)
    item, job = store.enqueue("analysis", {"kind": "iv"})
    store.cancel(job["id"])
    assert store.claim() is None
    assert store.get_job(job["id"])["state"] == "cancelled"


def test_recovery_marks_orphan_running_failed_without_retry(tmp_path):
    store = Store(tmp_path)
    item, job = store.enqueue("analysis", {"kind": "iv"})
    store.claim()
    assert store.recover_interrupted() == 1
    failed = store.get_job(job["id"])
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "interrupted"
    assert store.claim() is None


def test_managed_artifact_never_overwrites_and_detects_tampering(tmp_path):
    store = Store(tmp_path)
    folder = store.job_dir("00000000-0000-4000-8000-000000000001")
    folder.mkdir()
    file = folder / "metric.csv"
    file.write_bytes(b"value\n1\n")
    artifact = store.register_artifact(file, "table")
    assert store.artifact_path(artifact["id"]).read_bytes() == b"value\n1\n"
    file.write_bytes(b"value\n2\n")
    with pytest.raises(ValueError, match="hash"):
        store.artifact_path(artifact["id"])
    with pytest.raises(ValueError):
        store.managed_path("../escape")


def test_profile_publication_is_immutable_and_revision_ids_are_separate(tmp_path):
    store = Store(tmp_path)
    manifest = {"profile_id": "00000000-0000-4000-8000-000000000001", "revision": 1, "status": "draft"}
    store.save_profile(manifest, [{"state_id": "one"}])
    published = {**manifest, "status": "published", "profile_hash": "abc"}
    store.save_profile(published, [{"state_id": "one"}], replace_draft=True)
    with pytest.raises(ValueError, match="immutable"):
        store.save_profile(manifest, [], replace_draft=True)
    assert store.get_profile(manifest["profile_id"], 1)["manifest"]["status"] == "published"
