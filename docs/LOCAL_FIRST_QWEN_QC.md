# Local-First QWEN QC Inspection

## Design Principles

1. **Local-first storage**: all standard photos and production captures are saved to device/server storage before any cloud operation.
2. **On-device primary path**: MNN inference on the Android device is the default. Cloud is a fallback, not the primary path.
3. **Fail-closed**: any uncertainty, parse error, or timeout returns `review_required` — never `pass`.
4. **On-device FAIL is final** (§4.5.4): a `fail` from on-device inference cannot be escalated to cloud for a `pass` result.
5. **Explicit cloud consent**: images are never sent to cloud services without `cloudEnabled=true` AND `allowSendImages=true`.

## Inspection Flow

```
1. Capture production photo              → saved locally (CAP_{id}_{ts}_{uuid}.jpg)
2. Load standard reference photos        → fetched from local storage
3. Build QC prompt                       → QcPromptBuilder (prompt version: qwen-qc-v1)
4. Run on-device inference               → MnnQwenInspector via MNN JNI
   ├── FAIL         → return fail (final, §4.5.4)
   ├── PASS + high confidence → return pass
   └── uncertain / low confidence / error
       ├── cloud enabled → DashScope API (with fallback flag set)
       └── cloud disabled → return review_required
5. Parse & validate result               → QcResultParser (§4.3.5)
6. Store result                          → local Room DB + optional backend sync
```

## QC Point Contract

Each inspection run receives a list of `QcPointInput` objects with:
- `qcPointId`: canonical ID (e.g. `QC-01`)
- `qcPointCode`: short code
- `name`: human-readable label
- `description`: rule description

The parser enforces that the model's output:
- Contains only IDs present in the input list (hallucinated IDs are rejected)
- Covers all input IDs (missing IDs are filled as `review_required`)
- Has confidence values in [0.0, 1.0] (out-of-range values are clamped)

## Result States

| State             | Meaning                                                       |
|-------------------|---------------------------------------------------------------|
| `pass`            | All QC points passed with sufficient confidence               |
| `fail`            | One or more QC points failed; on-device result is final       |
| `review_required` | Uncertain, parse error, timeout, or model not provisioned     |

## Backend API

The Python FastAPI backend (see `src/api/`) exposes REST endpoints for:
- Managing `ProductStandard` and `QCPoint` definitions
- Recording `CapturePhoto` and `InspectionRun` results
- Cross-tenant isolation (all queries filter by `tenant_id`)

See [API_CONTRACT.md](API_CONTRACT.md) for endpoint details.

## Cloud Fallback Configuration

| Config key              | Default | Effect                                      |
|-------------------------|---------|---------------------------------------------|
| `cloudEnabled`          | false   | Master switch for cloud fallback            |
| `allowSendImages`       | false   | Second guard: images only sent if also true |
| `onDeviceFailIsFinal`   | true    | Prevents cloud from overriding a fail       |
| `minConfidence`         | 0.82    | Below this triggers fallback                |
| `onDeviceTimeoutMs`     | 10000   | Timeout for on-device inference             |
