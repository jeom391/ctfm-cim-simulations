import pytest
from httpx import ASGITransport, AsyncClient
from ctfm_api.app import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def client(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp("api-storage"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


async def test_upload_uses_managed_id_and_not_user_filename(client):
    response = await client.post("/api/v1/files", files={"files": ("../../source.csv", b"time,current,gate\n6,0.00001,0\n", "text/csv")})
    assert response.status_code == 201, response.text
    saved = response.json()["files"][0]
    assert saved["name"] == "source.csv"
    assert len(saved["sha256"]) == 64
    assert "path" not in saved
    assert saved in (await client.get("/api/v1/files")).json()["items"]


@pytest.mark.parametrize("filename,data", [
    ("old.xls", b"excel"), ("fake.xlsx", b"not a ZIP"),
    ("~$temporary.xlsx", b"tmp"), ("code.exe", b"binary"),
])
async def test_unsupported_upload_has_no_persisted_success(client, filename, data):
    response = await client.post("/api/v1/files", files={"files": (filename, data)})
    assert response.status_code == 422
    assert "error" in response.json()


async def test_missing_profile_rejected_before_enqueue(client):
    import json
    from pathlib import Path
    fixture = Path(__file__).resolve().parents[3] / "packages/contracts/fixtures/experiment-baseline.request.json"
    response = await client.post("/api/v1/experiments", json=json.loads(fixture.read_text()))
    assert response.status_code == 404
    assert (await client.get("/api/v1/jobs")).json()["items"] == []


async def test_analysis_requires_existing_files_and_explicit_mapping(client):
    response = await client.post("/api/v1/analyses", json={"kind":"iv","inputs":[{"file_id":"00000000-0000-4000-8000-000000000001","condition_id":"A1","device_id":"d1","column_mapping":{},"units":{}}],"settings":{}})
    assert response.status_code in (404,422)
    assert (await client.get("/api/v1/jobs")).json()["items"] == []

@pytest.mark.parametrize("manifest",[[],None])
async def test_profile_import_rejects_nonobject_manifest(client,manifest):
    import io,json,zipfile
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as archive:
        archive.writestr("manifest.json",json.dumps(manifest))
        archive.writestr("states.csv","unused")
    response=await client.post("/api/v1/profiles/import",files={"file":("profile.zip",buffer.getvalue())})
    assert response.status_code==422,response.text
