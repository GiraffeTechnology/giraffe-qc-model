# False-Pass Incident Response &amp; Requalification (PR 28)

Closes the production safety loop. If a false pass is discovered after L3
`controlled_active` is enabled, the affected scope is suspended and a new
qualification is required before L3 can be restored.

> **False pass is P0.** A confirmed false pass suspends `controlled_active` for
> the affected scope. **L2 `production_assisted` remains human-final** and can
> continue. **Requalification is required to restore L3.** Old qualification
> reports cannot restore L3 after a confirmed false pass. Mocked tests prove
> workflow only, not real visual accuracy.

## Loop

```
report incident  → (supervisor) confirm false pass
  → auto-create P0 scope suspension (controlled_active_suspended)
  → auto-create requalification requirement (prior approved report is NOT mutated)
  → readiness controlled_active blocked by active_false_pass_suspension (L3 only)
new approved, threshold-meeting, production-eligible qualification report
  (created after confirmation)
  → supervisor lifts suspension → requirement satisfied → L3 restorable
```

## Confirmation

`confirm_incident` decisions: `confirmed_false_pass` (identity + reason required)
→ suspend + require requalification; `rejected_not_false_pass` (identity + reason)
→ no suspension; `needs_more_evidence` → stays `triage_pending`. Every action
appends an immutable audit event.

## Suspension &amp; readiness

A confirmed false pass creates an **active** `controlled_active_suspended`
suspension for the incident's scope. The readiness gate adds a P0 check
`active_false_pass_suspension` to the L3 blocking set:

```json
{
  "controlled_active_allowed": false,
  "blocking_checks": ["active_false_pass_suspension"],
  "checks": [{"id": "active_false_pass_suspension", "passed": false, "severity": "P0", "blocking_items": [...]}]
}
```

`production_assisted_allowed` is **unaffected** — L2 stays available.

Ambiguous scope (no sku/station/detection point) suspends the **broader**
pack-level scope (fail closed).

## Lift rules

`lift_suspension` requires an identity, a reason, and a
`requalification_report_id`. The report is rejected unless it is:

- for the same training pack;
- **supervisor-approved**;
- **threshold-meeting** (any false pass above threshold → rejected);
- **created after the incident confirmation** (an old report cannot restore L3);
- produced by a **production-eligible** provider (no mock/fake/stub/skeleton
  restore).

On a valid lift the suspension becomes `lifted`, the requalification requirement
is marked `satisfied`, and audit events are appended. The original suspension
record is preserved.

## Data model / migration

`alembic/versions/016_qc_incident_response_requalification.py` adds
`qc_quality_incidents`, `qc_scope_suspensions`,
`qc_requalification_requirements`, and the append-only `qc_incident_audit_events`.
Verified `upgrade → downgrade → upgrade` clean. Prior approved qualification
reports are never mutated or deleted.

## API

```
POST /api/qc/incidents
GET  /api/qc/incidents/{incident_id}
POST /api/qc/incidents/{incident_id}/confirmation
GET  /api/qc/suspensions
POST /api/qc/suspensions/{suspension_id}/lift
GET  /api/qc/training-packs/{id}/readiness?target_mode=controlled_active   # now includes active_false_pass_suspension
```

UI: `/admin/qc-model/incidents`, `/admin/qc-model/incidents/{id}` (report,
confirm, lift; append-only audit; visible errors; tenant preserved).

## Tenant isolation

Incidents, suspensions, requalification requirements, and audit events are
tenant-scoped; a tenant cannot read/confirm/lift another tenant's records or use
another tenant's qualification report to lift.
