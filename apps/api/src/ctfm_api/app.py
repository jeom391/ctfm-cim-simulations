"""Versioned local research API backed by immutable artifacts and a durable queue."""
import io
import json
import threading
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, UploadFile, File, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from ctfm_contracts.check_experiment_contract import MAX_REQUESTED_RUNS, SCHEMA, SCHEMA_VERSION, validate_request
from ctfm_contracts.models import ExperimentRequest
from ctfm.profiles import ProfileManifest
from .contracts import AnalysisRequest, ProfileCreate, ProfileRevision, ProfilePublish, QueuedAnalysis, QueuedExperiment
from .models import Capabilities, Capability, ErrorResponse, HardwareControls
from .results import AnalysisResult, ExperimentResult, JobResult, JobList, FileUploadResult, FileList, FilePreview, AnalysisList, ExperimentList
from .storage import Store, encode, sha256, now
from .uploads import MAX_FILE_BYTES, validate_upload, checked_zip

class APIError(Exception):
    def __init__(self, status, code, message, field=None, details=None):
        self.status, self.code, self.message = status, code, message
        self.field, self.details = field, details

def error_response(status, code, message, field=None, details=None, headers=None):
    request_id = str(uuid4())
    body = ErrorResponse(error=dict(code=code, message=message, field=field, details=details or {}, request_id=request_id))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"),
                        headers={**(headers or {}), "X-Request-ID": request_id})

def capabilities():
    # Import verifies executable package availability; adapters do not claim fallback.
    try:
        from ctfm.simulation import engine_capabilities
        engines = engine_capabilities()
    except ImportError:
        engines = {name: dict(available=False, version=None, reason="adapter_not_installed") for name in ("torch_reference", "aihwkit_ideal", "neurosim")}
    version("ctfm-core")
    torch_available = engines["torch_reference"]["available"]
    properties = SCHEMA["properties"]
    controls = SCHEMA["allOf"][2]["then"]["properties"]["hardware"]["properties"]
    ppa_tiles, ppa_unsupported = [], {}
    if engines["neurosim"]["available"]:
        from ctfm.adapters.neurosim import engine_topology_support
        from ctfm.adapters.proxy_preset import proxy_preset
        from ctfm.simulation import MNIST_MLP_V1_LAYERS
        for tile in controls["tile_size"]["enum"]:
            preset = proxy_preset(tile)
            ok, why = engine_topology_support(MNIST_MLP_V1_LAYERS, tile, -(-preset["synapse_bit"] // preset["cell_bit"]))
            (ppa_tiles.append(tile) if ok else ppa_unsupported.__setitem__(str(tile), why))
    effect = lambda available, reason: Capability(available=available, version=None, reason=None if available else reason)
    return Capabilities(
        schema_version=SCHEMA_VERSION, profile_schema_version="1.0.0",
        models={"mnist_mlp_v1": effect(torch_available, "torch_unavailable")},
        engines=engines,
        effects={"d2d": effect(torch_available, "torch_unavailable"), "retention": effect(torch_available, "torch_unavailable"),
                 "adc": effect(torch_available, "torch_unavailable"),
                 # Manual-assumption C2C (schema_version 1.3.0): a per-profile-revision
                 # relative CV, never a measured CTFM cycle-to-cycle distribution.
                 "c2c": effect(torch_available, "torch_unavailable")},
        hardware=HardwareControls(tile_sizes=controls["tile_size"]["enum"], adc_bits=controls["adc_bits"]["enum"],
            adc_orders=controls["adc_order"]["enum"],
            range_policies=["validation_max_abs"],
            # Only engines whose ADC/tile combinations were compared against the
            # independent NumPy reference are advertised. AIHWKit earns its rows
            # from scripts/linux/verify_aihwkit_adc_combinations.py (18/18) and
            # still has to be available in *this* process to be listed.
            # Both ADC orders are compared against the independent NumPy model in
            # the same sweep, so the order is part of what is advertised: a caller
            # must not assume a verified bit/tile pair is verified in both orders.
            ppa_tile_sizes=ppa_tiles, ppa_unsupported=ppa_unsupported,
            validated_combinations=[{"tile_size": t, "adc_bits": b, "adc_order": o, "engine": name}
                                    for name in ("torch_reference", "aihwkit_ideal") if engines[name]["available"]
                                    for t in (64,128,256) for b in range(3,9)
                                    for o in controls["adc_order"]["enum"]] if torch_available else []),
        limits={"max_profiles": properties["profile_refs"]["maxItems"], "max_arrays": properties["arrays"]["maximum"],
                "max_year_points": properties["years"]["maxItems"], "max_years": properties["years"]["items"]["maximum"],
                "max_n_reprogram": properties["n_reprogram"]["maximum"], "max_requested_runs": MAX_REQUESTED_RUNS},
        supported_file_formats=["csv","xlsx"],
        warnings=["PPA is an assumed_proxy conditional estimate, never a validated CTFM chip result."])

def create_app(storage_root=None):
    app = FastAPI(title="CTFM measurement and CIM API", version="1.2.0",
                  responses={422: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
                  description="Explicit measurement review, immutable Device Profiles and queued scientific computation.")
    lock = threading.Lock()
    def storage():
        if not hasattr(app.state, "store"):
            with lock:
                if not hasattr(app.state, "store"):
                    app.state.store = Store(storage_root)
        return app.state.store
    app.state.storage = storage

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        issues = []
        for issue in error.errors():
            context = issue.get("ctx") or {}
            field = context.get("field") or ".".join(str(p) for p in issue["loc"] if p != "body") or None
            issues.append({"field": field, "rule": context.get("rule", issue["type"])})
        context = error.errors()[0].get("ctx") or {}
        return error_response(422, context.get("code", "invalid_request"), "Invalid request.", issues[0]["field"], {"issues": issues})

    @app.exception_handler(APIError)
    async def domain_error(request, error):
        return error_response(error.status, error.code, error.message, error.field, error.details)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(error.status_code, {400:"invalid_request",404:"not_found",405:"method_not_allowed"}.get(error.status_code,"http_error"), str(error.detail), headers=error.headers)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return error_response(404, "not_found", "The requested record does not exist.")

    @app.exception_handler(zipfile.BadZipFile)
    async def invalid_zip(request, error):
        return error_response(422, "invalid_request", "Invalid ZIP contents or CRC.")

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return error_response(422, "invalid_request", str(error))

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        return error_response(500, "internal_error", "An unexpected server error occurred.")

    app.get("/api/v1/capabilities", response_model=Capabilities)(capabilities)

    @app.post("/api/v1/files", status_code=201, response_model=FileUploadResult)
    async def upload(files: list[UploadFile] = File(...), store: Store = Depends(storage)):
        if not 1 <= len(files) <= 20:
            raise ValueError("Upload 1 to 20 files per request")
        prepared = []
        try:
            for file in files:
                data = await file.read(MAX_FILE_BYTES + 1)
                name, media_type = validate_upload(data, file.filename)
                prepared.append((data, name, media_type))
        finally:
            for file in files:
                await file.close()
        result = []
        for data, name, media_type in prepared:
            identifier = str(uuid4())
            relative = "uploads/" + identifier + Path(name).suffix.lower()
            store.managed_path(relative).write_bytes(data)
            record = dict(file_id=identifier, name=name, sha256=sha256(data), size_bytes=len(data), media_type=media_type, relative_path=relative, created_at=now())
            store.put_entity("file", identifier, record)
            result.append({k:v for k,v in record.items() if k != "relative_path"})
        return {"files":result}

    @app.get("/api/v1/files", response_model=FileList, response_model_exclude_unset=True)
    def files(store: Store = Depends(storage)):
        return {"items":[{k:v for k,v in row.items() if k != "relative_path"} for row in store.list_entities("file")]}

    @app.get("/api/v1/files/{identifier}/preview", response_model=FilePreview)
    def preview(identifier: UUID, sheet: str | None = None, store: Store = Depends(storage)):
        from ctfm.measurement import parse_table
        record = store.get_entity("file", str(identifier))
        data = store.managed_path(record["relative_path"]).read_bytes()
        if sha256(data) != record["sha256"]:
            raise ValueError("Source file hash mismatch")
        result = parse_table(data, record["name"], sheet)
        result["rows"] = result["rows"][:50]
        result["source_rows"] = result["source_rows"][:50]
        return dict(result, file_id=str(identifier), sheet=sheet or (result["sheets"][0] if result["sheets"] else None))

    @app.get("/api/v1/files/{identifier}/layout")
    def file_layout(identifier: UUID, kind: Literal["iv","retention"], sheet: str | None = None, store: Store = Depends(storage)):
        """Structure of the instrument layouts that /preview refuses (repeated Vg/Id/Ig blocks, independent P/E time axes).

        Nothing is selected here: the caller picks the block/segment or the four columns explicitly."""
        from ctfm.measurement.layouts import read_iv_blocks, read_retention_layout
        record = store.get_entity("file", str(identifier))
        data = store.managed_path(record["relative_path"]).read_bytes()
        if sha256(data) != record["sha256"]:
            raise ValueError("Source file hash mismatch")
        if kind == "iv":
            return dict(read_iv_blocks(data, record["name"], sheet), file_id=str(identifier))
        return dict(read_retention_layout(data, record["name"], sheet or "Raw Data"), file_id=str(identifier))

    @app.post("/api/v1/analyses", status_code=202, response_model=QueuedAnalysis)
    def analyze_request(request: AnalysisRequest, store: Store = Depends(storage)):
        for item in request.inputs:
            store.get_entity("file", str(item.file_id))
        item, job = store.enqueue("analysis", request.model_dump(mode="json", exclude_none=True))
        return {"analysis_id":item["id"],"job_id":job["id"]}

    @app.get("/api/v1/analyses", response_model=AnalysisList, response_model_exclude_unset=True)
    def analyses(store: Store = Depends(storage)):
        return {"items":store.list_entities("analysis")}

    @app.get("/api/v1/analyses/{identifier}", response_model=AnalysisResult, response_model_exclude_unset=True)
    def analysis(identifier: UUID, store: Store = Depends(storage)):
        return store.get_entity("analysis", str(identifier))

    def completed_analysis(store, identifier):
        if identifier is None:
            return None
        result = store.get_entity("analysis", str(identifier))
        if result["status"] != "succeeded":
            raise ValueError("Profile inputs must be successful analyses")
        return result

    @app.post("/api/v1/profiles", status_code=201, response_model=ProfileManifest, response_model_exclude_unset=True)
    def profile_create(request: ProfileCreate, store: Store = Depends(storage)):
        from ctfm.profiles import build_profile
        result = build_profile(request.condition_id, completed_analysis(store, request.state_analysis_id),
            request.selected_state_ids, completed_analysis(store, request.d2d_analysis_id),
            completed_analysis(store, request.retention_analysis_id), display_name=request.display_name)
        store.save_profile(**result)
        return JSONResponse(result["manifest"], status_code=201)

    @app.get("/api/v1/profiles")
    def profiles(status: Literal["draft","published"] | None = None, store: Store = Depends(storage)):
        return {"items":store.list_profiles(status)}

    @app.post("/api/v1/profiles/import", status_code=201, response_model=ProfileManifest, response_model_exclude_unset=True)
    async def profile_import(file: UploadFile = File(...), store: Store = Depends(storage)):
        from ctfm.profiles import parse_states_csv, validate_profile, compute_profile_hash
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise ValueError("Profile ZIP exceeds 100 MiB")
            with checked_zip(data, profile=True) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    raise ValueError("Profile manifest must be a JSON object")
                raw_states = archive.read("states.csv")
                if sha256(raw_states) != manifest.get("states_sha256"):
                    raise ValueError("Original states.csv SHA256 mismatch")
                states = parse_states_csv(raw_states)
            validate_profile(manifest, states)
            original = {key: manifest[key] for key in ("profile_id","revision","profile_hash","status")}
            manifest.update(profile_id=str(uuid4()), revision=1, status="draft", created_at=now(), published_at=None,
                            review={"reviewer":None,"reviewed_at":None,"note":None})
            manifest["extraction"]["import_origin"] = original
            manifest["profile_hash"] = compute_profile_hash(manifest)
            validate_profile(manifest, states)
            store.save_profile(manifest, states)
            return JSONResponse(manifest, status_code=201)
        finally:
            await file.close()

    @app.get("/api/v1/profiles/{identifier}/revisions/{revision}", response_model=ProfileManifest, response_model_exclude_unset=True)
    def profile(identifier: UUID, revision: int, store: Store = Depends(storage)):
        return JSONResponse(store.get_profile(str(identifier), revision)["manifest"])

    @app.get("/api/v1/profiles/{identifier}/revisions/{revision}/states")
    def profile_states(identifier: UUID, revision: int, store: Store = Depends(storage)):
        return {"items":store.get_profile(str(identifier), revision)["states"]}

    @app.post("/api/v1/profiles/{identifier}/revisions", status_code=201, response_model=ProfileManifest, response_model_exclude_unset=True)
    def profile_revision(identifier: UUID, request: ProfileRevision, store: Store = Depends(storage)):
        from ctfm.profiles import revise_profile
        record = store.get_profile(str(identifier), request.base_revision)
        result = revise_profile(**record, selected_state_ids=request.selected_state_ids,
                                revision=store.next_revision(str(identifier)), display_name=request.display_name)
        store.save_profile(**result)
        return JSONResponse(result["manifest"], status_code=201)

    @app.post("/api/v1/profiles/{identifier}/revisions/{revision}/publish", response_model=ProfileManifest, response_model_exclude_unset=True)
    def profile_publish(identifier: UUID, revision: int, request: ProfilePublish, store: Store = Depends(storage)):
        from ctfm.profiles import publish_profile
        record = store.get_profile(str(identifier), revision)
        result = publish_profile(**record, reviewer=request.reviewer, review_note=request.review_note)
        store.save_profile(result, record["states"], replace_draft=True)
        return JSONResponse(result)

    @app.get("/api/v1/profiles/{identifier}/revisions/{revision}/export")
    def profile_export(identifier: UUID, revision: int, store: Store = Depends(storage)):
        from ctfm.profiles import validate_profile, states_csv
        record = store.get_profile(str(identifier), revision)
        validate_profile(**record)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", encode(record["manifest"]))
            archive.writestr("states.csv", states_csv(record["states"]))
        return Response(buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition":f'attachment; filename="profile-{identifier}-r{revision}.zip"'})

    def resolve_measured_c2c(store, config):
        """The browser names a stored analysis; the server, not the request, supplies the number and its provenance."""
        from copy import deepcopy
        from ctfm.measurement.c2c import result_pin
        config = deepcopy(config)
        for ref in config["profile_refs"]:
            c2c = ref.get("c2c")
            if not c2c or c2c.get("source") != "measured_detrended":
                continue
            field = "profile_refs.c2c"
            if "cv_percent" in c2c or "provenance" in c2c:
                raise APIError(422,"c2c_server_fields","Measured C2C takes its value from the stored analysis; do not send cv_percent or provenance.",field)
            analysis = store.get_entity("analysis", c2c["analysis_id"])
            if analysis.get("kind") != "c2c_detrended" or analysis.get("status") != "succeeded":
                raise APIError(422,"c2c_analysis_invalid","analysis_id must name a succeeded measured C2C analysis.",field,{"analysis_id":c2c["analysis_id"]})
            if analysis.get("analysis_result_sha256") != result_pin(analysis):
                raise APIError(422,"c2c_analysis_tampered","The stored C2C analysis does not match its result hash.",field,{"analysis_id":c2c["analysis_id"]})
            program = analysis["program"]
            percent = program["primary"]["relative_residual_std_percent"]
            if program["status"] != "ok" or percent is None:
                raise APIError(422,"c2c_analysis_blocked","The Program deviation of this analysis is unavailable.",field,{"reason":program.get("blocked_reason")})
            profile_condition = store.get_profile(ref["id"], ref["revision"])["manifest"]["condition_id"]
            crossing = profile_condition != analysis["condition_id"]
            if crossing and not c2c.get("cross_condition_acknowledged"):
                raise APIError(422,"c2c_condition_mismatch","The analysis condition differs from the profile condition; acknowledge the cross-condition application explicitly.",field,
                               {"analysis_condition_id":analysis["condition_id"],"profile_condition_id":profile_condition})
            source = analysis["provenance"]
            c2c["cv_percent"] = percent
            c2c["provenance"] = dict(
                analysis_id=analysis["analysis_id"], analysis_result_sha256=analysis["analysis_result_sha256"], source_file_sha256=source["sha256"],
                source_filename=source["filename"], sheet=source["sheet"], device_id=source["device_id"], condition_id=analysis["condition_id"],
                analysis_version=analysis["analysis_version"], method=analysis["method"]["name"], primary_degree=analysis["method"]["primary_degree"],
                ddof=analysis["method"]["ddof"], cycle_min=source["cycle_min"], cycle_max=source["cycle_max"], cycle_count=source["cycle_count"],
                unit=source["unit"], program_relative_std_percent=percent, residual_lag1_correlation=program["primary"]["residual_lag1_correlation"],
                degree4_vs_degree3_change_percent=program["degree4_vs_degree3_change_percent"],
                measurement_conditions=analysis["measurement_conditions"], warnings=analysis["warnings"],
                is_pure_c2c_iid_estimate=False, erase_role="analysis_only",
                applied_to="every selected LTP/LTD state of the profile, both planes, independently drawn per reprogram/layer/plane",
                approved_assumption=True, cross_condition_acknowledged=bool(crossing), profile_condition_id=profile_condition)
        validate_request(config)
        return config

    @app.post("/api/v1/experiments", status_code=202, response_model=QueuedExperiment)
    def experiment_create(request: ExperimentRequest, store: Store = Depends(storage)):
        from ctfm.profiles import validate_profile
        config = request.root
        for ref in config["profile_refs"]:
            record = store.get_profile(ref["id"], ref["revision"])
            validate_profile(**record, published_required=True)
            for effect in ("d2d","retention"):
                if config["effects"][effect] and record["manifest"][effect]["status"] != "available":
                    raise APIError(422,"unavailable_measurement",f"{effect} measurement is not available.",f"effects.{effect}",{"profile_id":ref["id"]})
            if config["effects"]["retention"]:
                fit = record["manifest"]["retention"]["program_fit"]
                if fit["a"] + fit["b"] <= 0:
                    raise APIError(422,"unavailable_measurement","Retention reference current must be positive.","effects.retention")
        if config["engines"]["ppa"] == "assumed_proxy":
            from ctfm.adapters.neurosim import engine_topology_support
            from ctfm.simulation import MNIST_MLP_V1_LAYERS
            neurosim = capabilities().engines["neurosim"]
            if not neurosim.available:
                raise APIError(422,"unavailable_engine","The NeuroSim engine is not usable in this environment.","engines.ppa",{"reason":neurosim.reason})
            from ctfm.adapters.proxy_preset import proxy_preset
            preset = proxy_preset(config["hardware"]["tile_size"])
            supported, reason = engine_topology_support(MNIST_MLP_V1_LAYERS, config["hardware"]["tile_size"],
                                                 -(-preset["synapse_bit"] // preset["cell_bit"]))
            if not supported:
                raise APIError(422,"unsupported_ppa_configuration",reason,"hardware.tile_size",{"tile_size":config["hardware"]["tile_size"]})
        engine = config["engines"]["accuracy"]
        capability = capabilities().engines[engine]
        if not capability.available:
            raise APIError(422,"unavailable_engine","The requested accuracy engine is unavailable.","engines.accuracy",{"engine":engine,"reason":capability.reason})
        if config["checkpoint_id"]:
            checkpoint = store.get_entity("checkpoint", str(UUID(config["checkpoint_id"])))
            path = store.managed_path(checkpoint["relative_path"])
            if not path.is_file() or sha256(path.read_bytes()) != checkpoint["sha256"]:
                raise ValueError("Checkpoint hash mismatch")
        config = resolve_measured_c2c(store, config)
        item, job = store.enqueue("experiment", config)
        return {"experiment_id":item["id"],"job_id":job["id"]}

    @app.get("/api/v1/experiments", response_model=ExperimentList, response_model_exclude_unset=True)
    def experiments(store: Store = Depends(storage)):
        return {"items":store.list_entities("experiment")}

    @app.get("/api/v1/experiments/{identifier}", response_model=ExperimentResult, response_model_exclude_unset=True)
    def experiment(identifier: UUID, store: Store = Depends(storage)):
        return store.get_entity("experiment", str(identifier))

    @app.get("/api/v1/jobs", response_model=JobList, response_model_exclude_unset=True)
    def jobs(store: Store = Depends(storage)):
        return {"items":[{k:v for k,v in job.items() if k != "pid"} for job in store.list_jobs()]}

    @app.get("/api/v1/jobs/{identifier}", response_model=JobResult)
    def job(identifier: UUID, store: Store = Depends(storage)):
        return {k:v for k,v in store.get_job(str(identifier)).items() if k != "pid"}

    @app.post("/api/v1/jobs/{identifier}/cancel", status_code=202, response_model=JobResult)
    def cancel(identifier: UUID, store: Store = Depends(storage)):
        return {k:v for k,v in store.cancel(str(identifier)).items() if k != "pid"}

    @app.get("/api/v1/artifacts/{identifier}/download")
    def artifact(identifier: UUID, store: Store = Depends(storage)):
        path = store.artifact_path(str(identifier))
        record = store.get_entity("artifact", str(identifier))
        return FileResponse(path, filename=record["filename"], media_type=record["media_type"])

    web_dist = Path(__file__).resolve().parents[3] / "web/dist"
    if (web_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="web-assets")
    for route in ("/", "/measurements", "/simulator"):
        def web_page():
            if not (web_dist / "index.html").is_file():
                raise HTTPException(503,"Build apps/web before opening the UI.")
            return FileResponse(web_dist / "index.html")
        app.add_api_route(route, web_page, methods=["GET"], include_in_schema=False)
    return app

app = create_app()
