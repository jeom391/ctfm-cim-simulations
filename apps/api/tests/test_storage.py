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


@pytest.mark.parametrize('valid',[True,False])
def test_restart_registers_only_hash_verified_partial_checkpoints_and_is_retryable(tmp_path,monkeypatch,valid):
    from uuid import uuid4
    import json
    from ctfm_api.storage import sha256
    from ctfm_api.comparisons import create,write
    store=Store(tmp_path)
    with store.connection() as db:comparison=create(db,dict(common_settings={},cards=[]))
    item,job=store.enqueue('experiment',{})
    item['comparison_id']=comparison['comparison_id'];store.put_entity('experiment',item['id'],item,replace=True)
    comparison.update(lifecycle='running',experiment_id=item['id'],job_id=job['id'])
    with store.connection() as db:write(db,comparison)
    store.claim();out=store.job_dir(job['id']);out.mkdir()
    checkpoint=out/'checkpoint.pt';checkpoint.write_bytes(b'completed checkpoint')
    cpid=str(uuid4());pin=sha256(checkpoint.read_bytes()) if valid else '0'*64
    (out/'comparison-partial.json').write_text(json.dumps(dict(runs=[],checkpoint_id=cpid,checkpoint_filename='checkpoint.pt',provenance={'checkpoint':dict(checkpoint_id=cpid,model_id='mnist_mlp_v1',sha256=pin)})))
    finish=store.finish
    def interruption(*args,**kwargs):raise RuntimeError('supervisor stopped again before terminal commit')
    monkeypatch.setattr(store,'finish',interruption)
    with pytest.raises(RuntimeError,match='stopped again'):store.recover_interrupted()
    artifacts_before=store.list_entities('artifact')
    monkeypatch.setattr(store,'finish',finish)
    assert store.recover_interrupted()==1
    assert store.list_entities('artifact')==artifacts_before
    result=store.get_entity('experiment',item['id'])
    if valid:
        assert store.get_entity('checkpoint',cpid)['sha256']==pin
        assert len([a for a in result['artifacts'] if a['filename']=='checkpoint.pt'])==1
    else:
        with pytest.raises(KeyError):store.get_entity('checkpoint',cpid)
        assert result.get('checkpoint_id') is None
        assert not any(a['filename']=='checkpoint.pt' for a in result['artifacts'])
    assert store.get_job(job['id'])['state']=='failed'
