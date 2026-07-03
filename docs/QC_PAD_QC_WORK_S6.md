# S6 — Pad QC Work Page + Result Submission

Session 6 builds the operator QC Work page, its conversation/inspection log,
accurate runtime-readiness messaging, and the offline result-submission path
(review → Pad outbox → Server). It stacks on S5 (welcome / i18n / offline task
selection) and reuses the existing on-device capture + inspection pipeline.

## QC Work page layout (§8.2)

`OperatorQcWorkScreen` — landscape split, exact proportions:

```
┌───────────────────────────┬───────────────────────────┐
│                           │  4:3 standard reference    │
│                           ├───────────────────────────┤
│   4:3 live camera         │  conversation / log        │
│   (dominant, left)        │  (scrollable, §3.4 bubbles)│
│                           ├───────────────────────────┤
│                           │  input box · text/voice    │
└───────────────────────────┴───────────────────────────┘
```

- Left: dominant 4:3 camera (`CameraPreviewPane`, permission-gated, `fitAspect43`).
- Right-top: 4:3 `ReferenceImagePane` — decodes the installed standard photo
  from its local file (no image-loading library), placeholder otherwise.
- Right-middle: `ConversationLog` — §3.4 bubbles (OPERATOR right-aligned/primary;
  system kinds left-aligned; WARNING/ERROR distinct colors).
- Right-bottom: input box with a text/voice switch (voice is a controlled
  fallback — STT is not wired on device yet).

## Conversation content (§8.2)

`ConversationBuilder` (pure, localized through the language skill) produces the
required set: selected SKU, standard revision + bundle version, runtime-readiness
lines, system instructions, missing image/angle prompts, inspection progress,
detection-point results, warnings/errors, and operator messages.

## Runtime readiness (§8.3) — exact + fail-closed

`PadReadiness` resolves the exact states as i18n keys and **never overclaims**:

| State | When |
|---|---|
| `Local runtime not ready` | MNN native runtime not confirmed |
| `MNN native ready; model pending` | native ready, model not (yet) verified-loaded |
| `Model ready` | model loaded **and** on-device inference hardware-verified |
| `No standard installed` / `No SKU selected` | selection gaps |
| `Offline` / `Online` | connectivity |

The top state (`Model ready`) is gated on `inferenceVerified`, sourced from
`MnnRuntimeLoader.JNI_INFERENCE_WIRED` (PR30). While that tripwire is false the
Pad claims at most "MNN native ready; model pending" — it can never assert full
production readiness the native path hasn't earned. This does **not** re-verify
inference; it only consumes PR30's existing fail-closed flag.

## Result submission (§9)

```
capture → inspect → OperatorResultReviewScreen (mandatory human decision)
  → ResultSubmission (carries standard_revision_id + bundle_version)
  → PadOutbox (SQLite, idempotent on client_job_id)
  → OutboxUploader → SubmissionClient → Server (dedupes on client_job_id)
```

- The model never finalizes; the operator confirms accept / reject / review.
- Every submission carries `standardRevisionId` and `bundleVersion` so S4 can
  recompute the verdict against exactly the standard used.
- Inspection is fully offline — nothing on the QC path touches the network.
  Results persist in the outbox and drain from `OperatorSyncStatusScreen` when a
  window opens; the uploader is idempotent, so "Upload Now" is always safe.
- `HttpSubmissionClient` posts result **metadata only** over the factory LAN — it
  is not a QC-inference call and carries no cloud model traffic.

## Tests (JVM unit)

- `PadReadinessTest` — every exact state + the PR30 fail-closed gate.
- `ConversationBuilderTest` — the §8.2 content set is built and localized.
- `SubmissionTest` — submission provenance (revision/bundle), outbox idempotency,
  uploader drain + retry-on-failure, and the HTTP body/response encoding.

Compose screens and the SQLite/HTTP layers require the Android runtime and are
exercised on device; the readiness, conversation, and submission logic is covered
by the JVM suite above.
