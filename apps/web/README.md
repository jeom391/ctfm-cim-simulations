# CTFM CIM web application

React + TypeScript research workspace. Routes: `/`, `/measurements`, `/simulator`.
All calculations use the real `/api/v1` API; the browser never synthesizes accuracy or reimplements scientific extraction.

## Run

```powershell
cd apps/web
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. Start the repository API and worker separately. The API serves the production `apps/web/dist` after a build and must provide SPA fallback for the three routes.

```powershell
npm test
npm run build
```

Tests use Node 22.6+ native TypeScript stripping, with no test framework dependency. They verify baseline normalization, effect choices, bounds, resource budget, unavailable measurements/engines, supported ADC pairs, and explicit measurement mapping confirmation.

## Workflow

1. Upload CSV/XLSX, inspect sheet/first 50 original rows, explicitly map canonical columns and units, set device/condition and branch/direction metadata. Duplicate a dataset to split a source by original row bounds. Confirm each dataset before calculation.
2. Poll/cancel actual jobs. Inspect returned tables, exclusions, warnings, applied settings and artifact downloads. Advanced JSON settings allow explicit `crossing_segments` choices after reviewing ambiguous crossings.
3. Select measured pulse state IDs to create a draft. Optional linked D2D and Retention analyses are restricted to succeeded analyses with matching condition. Inspect pools/assumptions, record reviewer and review note, and explicitly confirm review to publish. Import/export ZIP and create a draft revision by changing selected state IDs/name.
4. Choose up to five published profiles and explicit pools/mappings/effects. The payload builder enforces request v1.1.0. Disabled effects become arrays=1, years=[0], null hardware; C2C/PPA remain unavailable. Retention requires actual Program fit and D2D actual CV. ADC support and engine availability come from capabilities. The server is authoritative for all validation.
5. Review actual run accuracy, signed losses, metrics, invalid/skipped runs, summary counts and reproducibility artifacts. Null is displayed as unavailable, never converted to zero. Checkpoint IDs can be reused.

The typed client is `src/lib/api/index.ts`. API errors show actionable messages/request IDs, without stack traces. No external font, UI kit, telemetry, authentication assumption or mocked production data is included.

## API type generation

After regenerating the server OpenAPI snapshot, run:

```powershell
npm run generate:api
npm run build
```

`src/lib/api/generated.ts` is generated from `../../packages/contracts/openapi/openapi.json`. The client and scientific request builder use the generated `ProfileManifest`, `ExperimentRequest`, and queued response types directly. Flexible result-table rows remain `Record<string, unknown>` because scientific result tables vary by analysis kind.
