"""Real HTTP contracts + real isolated worker, all source inputs explicitly synthetic."""
import io
import json
import zipfile
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from ctfm_api.app import create_app
from ctfm_worker.runner import run_once
from ctfm.profiles import validate_profile

pytestmark=pytest.mark.anyio
@pytest.fixture(scope="module")
def anyio_backend():return "asyncio"

async def test_upload_analysis_review_publish_import_revision_and_queue(tmp_path):
    app=create_app(tmp_path);store=app.state.storage()
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        datasets=[]
        for direction,gate,values in (("ltp",-6,(1e-6,2e-6,3e-6)),("ltd",6,(3e-6,2e-6,1e-6))):
            rows=["synthetic fixture; not measured","time,current,gate"]
            for i,value in enumerate(values):
                t=6+i*5
                rows += [f"{t},{value},0",f"{t+1},{value},0",f"{t+2},0,{gate/6}",f"{t+3},0,{gate}"]
            rows += ["30,0.000001,0","31,0.000001,0"]
            response=await client.post("/api/v1/files",files={"files":(direction+".csv",("\n".join(rows)+"\n").encode())})
            assert response.status_code==201,response.text
            file_id=response.json()["files"][0]["file_id"]
            preview=await client.get(f"/api/v1/files/{file_id}/preview")
            assert preview.status_code==200,preview.text
            assert preview.json()["source_rows"][0]==3
            datasets.append(dict(file_id=file_id,column_mapping=dict(time_s="time",id_a="current",vgs_v="gate"),units=dict(time_s="s",id_a="A",vgs_v="V"),condition_id="A1",device_id="synthetic-only",direction=direction,vds_v=.1,read_vgs_v=0))
        response=await client.post("/api/v1/analyses",json=dict(kind="pulse_states",inputs=datasets,settings={}))
        assert response.status_code==202,response.text
        analysis_id=response.json()["analysis_id"]
        assert run_once(store)
        result=(await client.get("/api/v1/analyses/"+analysis_id)).json()
        assert result["status"]=="succeeded",result
        assert len(result["states"])==6
        response=await client.post("/api/v1/profiles",json=dict(condition_id="A1",state_analysis_id=analysis_id,selected_state_ids=[s["state_id"] for s in result["states"]],display_name="SYNTHETIC TEST ONLY"))
        assert response.status_code==201,response.text
        draft=response.json();profile_id=draft["profile_id"]
        validate_profile(draft,result["states"])
        endpoint=f"/api/v1/profiles/{profile_id}/revisions/1"
        assert (await client.post(endpoint+"/publish",json=dict(reviewer="",review_note=""))).status_code==422
        response=await client.post(endpoint+"/publish",json=dict(reviewer="automated synthetic integration",review_note="Synthetic software verification only; not measured device data."))
        assert response.status_code==200,response.text
        published=response.json();validate_profile(published,result["states"],published_required=True)
        assert (await client.post(endpoint+"/publish",json=dict(reviewer="x",review_note="x"))).status_code==422
        exported=await client.get(endpoint+"/export")
        imported=await client.post("/api/v1/profiles/import",files={"file":("profile.zip",exported.content)})
        assert imported.status_code==201,imported.text
        clone=imported.json()
        assert clone["status"]=="draft" and clone["profile_id"]!=profile_id
        assert clone["extraction"]["import_origin"]["profile_hash"]==published["profile_hash"]
        validate_profile(clone,result["states"])
        archive=zipfile.ZipFile(io.BytesIO(exported.content));manifest=json.loads(archive.read("manifest.json"));manifest["display_name"]="tampered"
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w") as altered:
            altered.writestr("manifest.json",json.dumps(manifest));altered.writestr("states.csv",archive.read("states.csv"))
        assert (await client.post("/api/v1/profiles/import",files={"file":("tampered.zip",buffer.getvalue())})).status_code==422
        altered_bytes=io.BytesIO()
        with zipfile.ZipFile(altered_bytes,"w") as altered:
            altered.writestr("manifest.json",archive.read("manifest.json"))
            altered.writestr("states.csv",archive.read("states.csv").replace(b"\n",b"\r\n"))
        assert (await client.post("/api/v1/profiles/import",files={"file":("changed-lines.zip",altered_bytes.getvalue())})).status_code==422
        revised=await client.post(f"/api/v1/profiles/{profile_id}/revisions",json=dict(base_revision=1,selected_state_ids=[s["state_id"] for s in result["states"][:3]],display_name="Selected synthetic LTP"))
        assert revised.status_code==201,revised.text
        assert revised.json()["revision"]==2 and revised.json()["status"]=="draft"
        assert (await client.get(endpoint)).json()==published
        root=Path(__file__).resolve().parents[2]
        config=json.loads((root/"packages/contracts/fixtures/experiment-baseline.request.json").read_text())
        config["profile_refs"]=[dict(id=profile_id,revision=1)]
        response=await client.post("/api/v1/experiments",json=config)
        assert response.status_code==202,response.text
        job_id=response.json()["job_id"]
        assert (await client.post(f"/api/v1/jobs/{job_id}/cancel")).status_code==202
        assert (await client.get(f"/api/v1/jobs/{job_id}")).json()["state"]=="cancelled"
        config["effects"]["d2d"]=True
        assert (await client.post("/api/v1/experiments",json=config)).status_code==422
        artifact=result["artifacts"][0]
        download=await client.get(artifact["download_url"])
        assert download.status_code==200
        import hashlib
        assert hashlib.sha256(download.content).hexdigest()==artifact["sha256"]
