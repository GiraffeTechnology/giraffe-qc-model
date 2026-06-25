# QC Pad Conversational UI

PR11 introduces a full operator-facing Pad UI for factory QC operators supporting:
- Conversational/fuzzy text input in English, Chinese (Simplified), and Japanese
- Voice input with controlled fallback
- Image upload for inspection evidence
- LLM multilingual understanding via OpenClaw bridge
- Canonical English storage of all operator input
- Localized output in operator's preferred language
- Standard intake confirmation flow (LLM proposes, operator confirms before DB write)
- Inspection job creation and report viewing
- Landscape-first PWA with portrait blocking overlay

## Architecture

```
Operator Input (raw multilingual text)
    |
    v
QCAgentBridge.process()
    detect_language()  -> source_lang
    translate_text()   -> normalized_en (stored in DB)
    classify_qc_intent() -> intent + confidence
    extract_qc_checkpoints()
    localize_response() -> reply in operator's language
    |
    v
ActionCard (if confidence >= 0.50)
    |
    v
Operator Confirms (for standard mutations)
    |
    v
Service layer writes to DB
```

## Safety Rules

- **LLM output is never trusted directly.** All DB mutations go through service functions.
- **No standard activation without explicit operator confirmation.** The `/api/v1/pad/confirm_standard` endpoint requires an explicit `intake_id` from the operator.
- **No LLM-generated final verdict.** LLM is used only for language processing and intent classification, never for pass/fail decisions.
- **No fake pass.** The system never generates a pass/fail verdict without real checkpoint data.
- **Confidence threshold enforced.** Intent confidence < 0.50 returns a clarification request without any DB mutation.

## API Endpoints

### Web Routes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/pad/login` | Login page |
| POST | `/pad/login` | Submit login |
| POST | `/pad/logout` | Logout |
| GET | `/pad` | Main workspace |
| GET | `/pad/inspections/{job_id}` | Inspection view |
| GET | `/pad/inspections/{job_id}/report` | Inspection report |

### API Routes
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/pad/chat` | Conversational message processing |
| POST | `/api/v1/pad/voice` | Voice input (STT fallback) |
| POST | `/api/v1/pad/upload` | Image upload |
| GET | `/api/v1/pad/session` | Current session info |
| POST | `/api/v1/pad/language` | Update preferred language |
| POST | `/api/v1/pad/confirm_standard` | Explicit operator confirmation |
| POST | `/api/v1/pad/create_inspection_job` | Create inspection job |

## Demo Operators

| Username | Password | Language | Role |
|----------|----------|----------|------|
| operator_cn | operator_cn | zh-CN | operator |
| operator_en | operator_en | en | operator |
| reviewer_ja | reviewer_ja | ja | reviewer |
| admin_en | admin_en | en | admin |

## DB Models

- `qc_operator_profiles`: Operator credentials, display name, preferred language
- `qc_conversation_sessions`: Conversation session per operator per tenant
- `qc_conversation_messages`: Full audit trail of all messages (user + assistant turns)

## OpenClaw Bridge

In CI/tests, `FakeOpenClawLLMClient` is used (no network calls, deterministic):
- Language detection: Unicode range heuristics (Chinese: U+4E00-U+9FFF; Japanese: U+3040-U+30FF)
- Intent classification: keyword matching
- Translation: phrase substitution tables

In production, set `OPENCLAW_API_URL` to activate `RealOpenClawLLMClient`.

## PWA

- Manifest: `/static/pad_manifest.json` with `"orientation": "landscape"`
- Portrait mode: shows `#orientation-overlay` and disables `.qc-action-btn` elements
- Android: `android:screenOrientation="landscape"` in `AndroidManifest.xml`
