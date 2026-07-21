# Stage 2 external-drive inventory

Inventory date: 2026-07-15 (Asia/Hong_Kong)

Read-only discovery found one external 1 TB USB physical drive with an APFS
container and approximately 588 GB free. Two writable volumes are mounted:

| Candidate volume | Format | Ownership | Selection state |
|---|---|---|---|
| `N1_WORK` | APFS | disabled | **selected** |
| `Michael 1` | case-sensitive APFS | enabled | not selected |

The selected dedicated root is `/Volumes/N1_WORK/giraffe-stage2`, with `images`,
`workspace`, and `evidence` subdirectories. Selection-time free space was about
588 GB, sufficient for the system image, guest overlay, dependencies, fixtures,
and UI evidence.

A 64 MiB bounded write, flush, reopen, read-back, and SHA-256 comparison completed
successfully. The retained probe file is under the external root's `evidence`
directory. A repeated, script-generated result is recorded in
`sandbox_tests/reports/evidence/stage2/drive-probe.json`.

The initial observed write completed in about 1.66 seconds. The subsequent read
was served partly or wholly from cache, so neither timing is a sustained-device
speed measurement. They are not production-performance evidence. This check
establishes bounded mount/RW/permission integrity only.

A test on one APFS volume does not establish independent physical-drive
redundancy because both candidate volumes share the same physical device.
