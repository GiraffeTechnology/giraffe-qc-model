# Stage 2 external-drive inventory

Inventory date: 2026-07-14 (Asia/Hong_Kong)

Read-only discovery found one external 1 TB USB physical drive with an APFS
container and approximately 588 GB free. Two writable volumes are mounted:

| Candidate volume | Format | Ownership | Selection state |
|---|---|---|---|
| `N1_WORK` | APFS | disabled | not selected |
| `Michael 1` | case-sensitive APFS | enabled | not selected |

No Stage 2 files or speed-test data have been written. After Q1 and the target
volume are confirmed, record mount stability, permissions, a bounded RW test,
available capacity, and the dedicated Stage 2 root here. A test on one APFS volume
does not establish independent physical-drive redundancy because both volumes
share the same physical device.
