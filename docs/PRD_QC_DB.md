# PRD: QC Model Dedicated Database and Checkpoint-Driven Inspection System

## 1. Background

We are building a dedicated QC database and workflow for `giraffe-qc-model`.

The QC model must not work like a general visual chatbot. It must operate as a **checkpoint-driven visual inspection system**.

The first application example is an artificial flower accessory / brooch. An operator uploads an approved reference photo through WeChat, IM, Email, Pad, or Web, and provides inspection requirements such as:

1. Whether the stamen / flower center is centered.
2. Whether the stamen pearls and rhinestones match the required quantity.
3. Whether the petals have cracks, missing pieces, broken edges, or visible damage.

The system must extract these requirements, structure them, send them back to the operator for confirmation, and only write them into the approved QC standard database **after operator confirmation**.

The same system must also support inspection photos. For each inspection job, the QC model must compare the inspection photo against the approved standard and evaluate every approved checkpoint one by one.

The system must also detect obvious abnormalities outside the approved checklist, such as pearl color abnormality, pearl cracks, glue overflow, metal oxidation, stains, or other visible defects. These are stored as incidental findings and escalated for human review when necessary.

---

## 2. Core Product Principle

### 2.1 No-Guess QC Policy

The QC model must not guess.

For every approved checkpoint, the model must produce:

1. Expected requirement.
2. Observed visual evidence.
3. Comparison against the approved reference or approved rule.
4. `pass` / `fail` / `review_required` result.
5. Confidence score.
6. Evidence location where applicable (bbox, mask, crop, keypoint, color sample, or local image crop).

If a checkpoint cannot be visually verified, the result must be `review_required`. It must **never** default to `pass`.

### 2.2 LLM Role

The LLM can be used for:

1. Requirement extraction from operator text, voice transcript, IM messages, and email attachments.
2. Structuring the checklist draft.
3. Generating confirmation messages to the operator.
4. Generating human-readable QC reports.

The LLM must **not** be the only source of the QC decision. QC decision must come from: visual observation + checkpoint coverage + rule comparison + auditable evidence.

### 2.3 Vision Role

The vision layer must perform actual visual inspection tasks:

1. Object counting.
2. Position / alignment comparison.
3. Visual similarity comparison.
4. Defect detection.
5. Color abnormality detection.
6. Crack / broken edge / missing piece detection.
7. Incidental anomaly detection.

### 2.4 Rule Engine Role

The rule engine must combine approved checkpoint rules and visual observations to produce deterministic checkpoint-level results. The final result must be derived from checkpoint results and incidental findings, not from free-form LLM judgment.

---

## 3. Target Workflow

### 3.1 Standard Intake Workflow

Operator sends reference photo and requirements via WeChat, IM, Email, Pad, or Web.

**Example operator message:**
```
This is the approved reference sample. Inspection points:
1. Check whether the stamen is centered.
2. Check whether pearls and rhinestones match the required quantity.
3. Check whether petals have cracks or missing pieces.
```

The system must:

1. Store raw message.
2. Store media assets.
3. Transcribe voice if the message is voice.
4. Parse and normalize operator requirements.
5. Generate a structured QC checklist draft.
6. Send the structured checklist back to the operator for confirmation.
7. Wait for operator confirmation or modification.
8. After confirmation, create a new approved QC standard version.

**The system must not write extracted draft requirements directly into the approved standard table.**

### 3.2 Operator Confirmation Message

The system sends a confirmation like:
```
Please confirm the extracted QC requirements:
Product: Artificial Flower Accessory
Reference Photo: 1 image received
Checkpoints:
1. Stamen centering
   - Target: flower center / stamen cluster
   - Rule: centered within four-petal silhouette
   - Severity: major
2. Pearl count
   - Expected count: 3
   - Severity: critical
3. Rhinestone count
   - Expected count: please confirm
   - Severity: critical
4. Petal integrity
   - Rule: no visible crack, missing piece, broken edge, or structural damage
   - Severity: critical
Please reply CONFIRM or provide corrections.
```

### 3.3 Inspection Workflow

For each inspection job:

1. Operator uploads inspection image.
2. System identifies SKU and active standard version.
3. System loads approved reference photo and approved checkpoints.
4. Model inspects every approved checkpoint.
5. Rule engine generates checkpoint-level result.
6. System checks for incidental findings outside the approved checklist.
7. System produces final result: `pass` / `fail` / `review_required`.
8. Human reviewer can override or confirm.
9. Final report is generated.
10. Results are stored for future training / audit.

---

## 4. Required Status Machines

### 4.1 Standard Intake Status

```
received → parsed → pending_operator_confirmation → confirmed → approved_standard_version
pending_operator_confirmation → modified → pending_operator_confirmation
pending_operator_confirmation → rejected
```

### 4.2 Inspection Job Status

```
created → media_uploaded → model_running → ai_done
  → review_required / passed / failed
  → human_reviewed
  → final_report_generated
```

If any checkpoint is not fully observed, final result cannot be `pass`.

---

## 5. Database Schema

### 5.1 `qc_product_sku` — Product / SKU master

| Field | Type | Notes |
|---|---|---|
| id | Integer PK | |
| sku_code | String(128) | unique |
| product_name | String(256) | |
| category | String(128) | e.g. `artificial_flower_accessory` |
| supplier_id | Integer | nullable |
| customer_id | Integer | nullable |
| status | String(32) | `active` / `inactive` |
| created_at | DateTime | |
| updated_at | DateTime | |

### 5.2 `qc_channel_message` — Raw operator messages

| Field | Type | Notes |
|---|---|---|
| id | Integer PK | |
| channel_type | String(32) | `wechat` / `whatsapp` / `email` / `web` / `pad` / `other` |
| channel_message_id | String(256) | external message ID |
| sender_id | String(128) | |
| sender_name | String(256) | |
| raw_text | Text | never overwritten |
| normalized_text | Text | voice transcript or cleaned text |
| message_type | String(32) | `text` / `voice` / `image` / `file` / `mixed` |
| received_at | DateTime | |
| processing_status | String(32) | `received` / `parsed` / `pending_confirmation` / `confirmed` / `rejected` |
| created_at | DateTime | |
| updated_at | DateTime | |

### 5.3 `qc_media_asset` — Reference photos, inspection photos, voice files

Key fields: `media_type`, `media_role`, `storage_uri`, `sha256` (for deduplication), `file_size`, `mime_type`, `width`, `height`, `exif_json`.

Images are stored as URIs. Raw binary is never stored in the database.

### 5.4 `qc_standard_intake` — One intake session before approval

`extracted_json` is draft content only. It cannot be treated as an approved QC standard until operator confirmation.

### 5.5 `qc_operator_confirmation` — Operator confirmation record

Approved standard can only be generated after `confirmation_status` is `confirmed` or `modified`.

### 5.6 `qc_standard_version` — Approved QC standard version

Versioned, never overwritten. Only one active standard per SKU in MVP.

### 5.7 `qc_standard_media` — Reference media bound to a standard version

One primary reference image required for MVP.

### 5.8 `qc_check_point` — Approved inspection checkpoint

Example codes: `STAMEN_CENTERING`, `PEARL_COUNT`, `RHINESTONE_COUNT`, `PETAL_INTEGRITY`.

### 5.9 `qc_check_rule` — Executable rule for a checkpoint

Example count rule:
```json
{
  "rule_type": "count",
  "expected_value_json": {"pearl": 3, "rhinestone": 8},
  "fail_condition_json": {
    "missing_component": true,
    "extra_component": true,
    "obvious_displacement": true
  }
}
```

### 5.10 `qc_inspection_job` — One QC inspection job

Key counters: `checkpoint_total`, `checkpoint_observed_count`, `checkpoint_pass_count`, `checkpoint_fail_count`, `coverage_rate`, `has_unchecked_checkpoint`.

`coverage_rate` must be 100% before final result can be `pass`.

### 5.11 `qc_inspection_media` — Inspection media bound to a job

### 5.12 `qc_model_result` — Model-level output

`no_guess_policy_applied` must always be `true`. Raw model output is preserved.

### 5.13 `qc_checkpoint_result` — Per-checkpoint result

One row per approved checkpoint per job. Missing row is a system error.

Fields: `expected_json`, `observed_json`, `comparison_json`, `result`, `confidence_score`, `evidence_type`, `evidence_json`, `verification_status`, `failure_reason`.

`verification_status` != `observed` → result must be `review_required`.

### 5.14 `qc_incidental_finding` — Abnormalities outside approved checklist

`is_within_approved_checklist` is normally `false`. Major or critical findings trigger `review_required` or `fail`.

### 5.15 `qc_human_review` — Human review or override

Statuses: `confirmed` / `overridden` / `rejected` / `needs_reinspection`.

### 5.16 `qc_final_report` — Generated QC report

### 5.17 `qc_training_sample` — Training data from real inspection

Sample types: `pass_case` / `fail_case` / `review_case` / `incidental_finding` / `correction`.

### 5.18 `qc_audit_event` — Audit trail

Records: standard creation, operator confirmation, standard version activation, inspection finalization, human override.

---

## 6. Artificial Flower Accessory MVP Standard

**SKU:** `FLOWER-BROOCH-001`  
**Product:** Pearl Rhinestone Artificial Flower Brooch  
**Category:** `artificial_flower_accessory`  
**Standard Version:** `v1.0`

### 6.1 STAMEN_CENTERING

- **Severity:** major  
- **Method:** alignment  
- **Pass Rule:** The stamen cluster must be visually centered within the four-petal flower silhouette. Obvious shift causes fail.
- **Required observed fields:** `flower_silhouette_center`, `stamen_cluster_center`, `offset_direction`, `offset_level`

### 6.2 PEARL_COUNT

- **Severity:** critical  
- **Method:** counting  
- **Pass Rule:** Exactly 3 visible pearls. Missing, extra, cracked, or detached pearls fail.
- **Expected:** `{"pearl_count": 3}`

### 6.3 RHINESTONE_COUNT

- **Severity:** critical  
- **Method:** counting  
- **Pass Rule:** Exactly 8 rhinestones. Missing, extra, detached, or displaced rhinestones fail.
- **Expected:** `{"rhinestone_count": 8}`

### 6.4 PETAL_INTEGRITY

- **Severity:** critical  
- **Method:** defect_detection  
- **Pass Rule:** All 4 petals free from visible cracks, missing pieces, broken edges, or structural damage.
- **Required observations per petal:** `petal_1_top_left`, `petal_2_top_right`, `petal_3_bottom_right`, `petal_4_bottom_left`

---

## 7. Incidental Findings Policy

The model must report obvious abnormalities even if outside the approved checklist:

- Pearl color abnormality
- Pearl surface crack
- Pearl coating damage
- Yellowed petal
- Metal stamen oxidation
- Glue overflow
- Visible dirt or stain
- Broken or loose component

---

## 8. Final Decision Policy

| Condition | Final Result |
|---|---|
| Any critical or major checkpoint fails | `fail` |
| Any checkpoint not observed / occluded / low-confidence / unsupported | `review_required` |
| All checkpoints pass + critical incidental finding | `fail` or `review_required` |
| All checkpoints pass + major incidental finding | `review_required` |
| All checkpoints pass + no major/critical incidental findings | `pass` |

**`pass` requires:**
```
checkpoint_total == checkpoint_observed_count
checkpoint_fail_count == 0
checkpoint_review_required_count == 0
critical_incidental_finding_count == 0
major_incidental_finding_count == 0
coverage_rate == 100%
```

---

## 9. Report Format

```
QC Result: PASS / FAIL / REVIEW_REQUIRED

1. Approved Checklist Inspection
   1.1 Stamen Centering: PASS / FAIL / REVIEW_REQUIRED
       Expected: ...
       Observed: ...
       Evidence: ...
       Confidence: ...
       Reason: ...
   ...

2. Incidental Findings
   2.1 Finding Type: ...
       Target Part: ...
       Severity: ...
       Evidence: ...
       Confidence: ...
       Human Review Required: ...

3. Final Decision
   Final result: ...
   Final reason: ...
   Manual review reason (if any): ...
```

---

## 10. Engineering Constraints

1. Do not break existing APIs or tests.
2. Follow the existing coding style (SQLAlchemy 2.x `Mapped[]` style).
3. Do not fake final QC pass results.
4. Vision model integration is mocked deterministically in tests (clearly marked `TEST_FIXTURE`).
5. Production logic must preserve `review_required` when model cannot observe a checkpoint.
6. All new tables have timestamps.
7. All important state transitions create audit events.
8. The system is ready for future IM / WeChat / Email adapters via the adapter-neutral intake service.

---

## 11. Definition of Done

1. `docs/PRD_QC_DB.md` exists. ✓
2. Migrations run successfully from clean database. ✓
3. Seed data creates FLOWER-BROOCH-001 SKU and active standard version. ✓
4. Operator intake cannot create approved standard without confirmation. ✓
5. Inspection job always creates one checkpoint result per approved checkpoint. ✓
6. Final result cannot be `pass` unless all checkpoints observed and passed. ✓
7. Incidental findings stored separately from checklist results. ✓
8. Major/critical incidental findings trigger `review_required` or `fail`. ✓
9. Tests cover all core workflows. ✓
10. All tests pass. ✓
11. Developer guide explains how to run the QC DB workflow locally. ✓
