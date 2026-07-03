# VERIFICATION — Task 03: Offline Standard Sync

> Branch: `claude/task03-offline-standard-sync` (PR #32). Scope: Python backend +
> Android Pad. Design: `docs/offline-sync.md`.

## Environment disclosure (read first)

This ran in a remote container with **no OPPO Pad and no ADB**. Per Hard
Constraint 6 (raw output; no paraphrased "it works"), the two-sided flows are
split:

- **Server half** (acceptance #1, #2) and the **Pad importer/outbox logic**
  (acceptance #8) are fully executed here with raw output below.
- **On-device Pad items** (#3, #4, #5, #6, #7) require the physical Pad and a
  running server; they are marked **PENDING (hardware)** with an operator runbook.
  Their core logic is proven by the JVM unit tests, but the end-to-end adb/device
  evidence must be captured on the Pad.

| # | Item | Verdict |
|---|------|---------|
| 1 | Server: export bundle for tenant with ≥2 SKUs; show manifest/checksums/signature | ✅ **PASS** (executed) |
| 2 | Server: full Python suite green incl. new bundle/signing + tamper tests | ✅ **PASS** (executed) |
| 3 | Pad: import via inbox (adb push) → success, version updated, SKUs inspectable | ⏳ **PENDING (hardware)** |
| 4 | Pad: tampered bundle rejected, prior standards intact | ⏳ **PENDING (hardware)**; logic proven by unit tests |
| 5 | Pad: downgrade bundle rejected | ⏳ **PENDING (hardware)**; logic proven by unit tests |
| 6 | Pad: sync-window pull against running server | ⏳ **PENDING (hardware + server)** |
| 7 | Pad: offline job → outbox → sync upload → server shows job → re-upload deduped | ⏳ **PENDING (hardware + server)**; dedupe proven server-side + unit tests |
| 8 | Android unit tests green incl. importer sig/checksum/rollback | ✅ **PASS** (executed) |

---

## Item 1 — Server bundle export ✅ PASS

Export for tenant `acme` with 2 trained SKUs (each: active revision, 2 detection
points, 1 photo). Raw output:

```
=== export metadata ===
bundle_version: 1 | sku_count: 2 | fingerprint: 5a116d7c6cbfd0cf
archive: acme_all_v1.tar.gz sha256: 5502039f56cff254a1894702b1cba79b ...

=== archive members ===
  manifest.json  (1650 bytes)
  checksum.sha256  (258 bytes)
  bundle.sig  (88 bytes)
  photos/sku-1/sku-1.jpg  (8 bytes)
  photos/sku-2/sku-2.jpg  (8 bytes)

=== manifest.json (excerpt) ===
{ "bundle_format_version": 1, "bundle_version": 1, "tenant_id": "acme",
  "line_scope": "", "signing_key_fingerprint": "5a116d7c6cbfd0cf", "sku_count": 2 }
  skus: [('WIDGET-001','Blue Widget',2,1), ('WIDGET-002','Red Widget',2,1)]

=== checksum.sha256 ===
fc35adc98c50f09a79c5bc6d02d0df43fc7ccde7e75ff0a19ab299fe49e2ca8d  manifest.json
24a7a22478172b65a66b7b56346b21a08aa4f25956e22cc9c99f7a1aaa7bb214  photos/sku-1/sku-1.jpg
4b94a90bb214d2117a8a6da80bb2a55af20dd54f4f655dc66db68465326c4b9f  photos/sku-2/sku-2.jpg

=== bundle.sig (base64 Ed25519) ===
/7GxYVsWkdn1fbyZgxTkRrZIaMCwWfc5OrxqbQagcQ2qxI2UvUy46vjAXkK1rP083UJzdclP8VT4BbwHrz3EAA==

=== verify_bundle_archive: PASS (signature+checksums+manifest) ===
```

## Item 2 — Full Python suite green incl. tamper tests ✅ PASS

```
$ LANG=C.utf8 uv run pytest -q
818 passed, 6 skipped, 1 warning in 68.78s

$ uv run pytest tests/test_offline_bundle_sync.py -q
11 passed
```

`tests/test_offline_bundle_sync.py` covers: export (2 SKUs) manifest/checksum/
signature; **tampered manifest → rejected**; **tampered photo → rejected**; wrong
key → rejected; only-active-revisions-ship; missing-photo fail-closed; monotonic
version + `/latest`; idempotent reverse-sync (dedupe on re-upload); unknown
sku/point rejected; API export/latest/download/public-key; API batch idempotent.

## Item 8 — Android unit tests green ✅ PASS

```
$ export ANDROID_HOME=/home/user/android-sdk
$ LANG=C.utf8 gradle :app:testPadLocalDebugUnitTest --console=plain
BUILD SUCCESSFUL
tests=143 failures=0 errors=0

  com.giraffetechnology.qc.sync.BundleVerificationTest  tests=5  failures=0
  com.giraffetechnology.qc.sync.BundleImporterTest      tests=5  failures=0
  com.giraffetechnology.qc.sync.OutboxUploaderTest      tests=5  failures=0
```

- **BundleVerificationTest**: valid bundle verifies+parses; tampered manifest
  rejected; tampered photo rejected; wrong public key rejected; missing signature
  rejected.
- **BundleImporterTest**: installs standards + extracts photos; re-import same
  version is idempotent no-op; **downgrade rejected, prior standards intact**;
  tampered bundle rejected, prior standards intact; **store failure rolls back to
  previous standards** (all-or-nothing).
- **OutboxUploaderTest**: enqueue idempotent; uploads pending; server-side dedupe;
  rejected job marked failed not uploaded; **network failure mid-drain leaves
  remainder pending (resumable)**.

Full APK also assembles (compiles the on-device SQLite store + graph wiring):
```
$ gradle :app:assemblePadLocalDebug   → BUILD SUCCESSFUL
```

## Legacy gen-2 untouched (Hard Constraint 5)

Reverse sync is built on `qc_inspection_jobs` (+ checkpoint/media/final-report).
No new code references the deprecated `sync_targets`/`sync_jobs` tables.

---

## Operator runbook — items 3, 4, 5, 6, 7 (PENDING, requires the Pad + server)

Prereqs: install the Task 03 build on the Pad; run a server reachable from the
Pad's LAN with a signing key configured whose **public** half matches
`assets/qc_bundle_public_key.b64` (or replace the asset via
`GET /api/v1/qc/bundles/public-key`).

```bash
# Server: export a bundle (tenant with >=2 active SKUs)
curl -X POST "$SERVER/api/v1/qc/bundles/export" -H 'content-type: application/json' \
     -d '{"tenant_id":"acme"}'
BUNDLE_ID=...   # from response
curl -o bundle.tar.gz "$SERVER/api/v1/qc/bundles/$BUNDLE_ID/download?tenant_id=acme"

# Item 3 — inbox import
adb shell mkdir -p /sdcard/giraffe_qc/inbox
adb push bundle.tar.gz /sdcard/giraffe_qc/inbox/
adb shell am start -n com.giraffetechnology.qc/.MainActivity   # trigger scan (or Sync action)
adb logcat -d -s InboxScanner PadSyncManager | tee item3.log
# PASS: "bundle audit: ... outcome=imported", version indicator updated, SKUs inspectable.

# Item 4 — tampered bundle
python3 - <<'PY'  # flip one byte in a photo
import tarfile,io,sys; ...  # (or edit manifest) then repack
PY
adb push tampered.tar.gz /sdcard/giraffe_qc/inbox/ && adb logcat -d -s InboxScanner | tee item4.log
# PASS: outcome=rejected (signature/checksum), file moved to failed/, prior standards intact.

# Item 5 — downgrade
# push a bundle with a lower bundle_version than installed
adb logcat -d -s InboxScanner | tee item5.log
# PASS: outcome=rejected downgrade_rejected; installed version unchanged.

# Item 6 — sync-window pull
# with the Pad on network, trigger the in-app Sync action (PadSyncManager.pullLatest)
adb logcat -d -s PadSyncManager | tee item6.log
# PASS: version check -> download -> import.

# Item 7 — offline job -> outbox -> upload -> dedupe
# run >=1 offline inspection so a job lands in the outbox, then trigger uploadOutbox:
adb logcat -d -s PadSyncManager | tee item7.log
curl "$SERVER/api/v1/qc/inspection-jobs/<job_uuid>?tenant_id=acme"   # server shows the job
# re-run uploadOutbox -> server returns duplicate; no second job server-side.
```

Paste the resulting `item{3..7}.log` and server API responses here with a binary
PASS/FAIL per item once captured on the Pad.
