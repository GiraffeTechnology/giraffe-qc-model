# Stage 2 QEMU aarch64 runbook

This runbook reproduces sandbox-only ARM64 CV evidence. It does not emulate a
Jetson GPU, CUDA/TensorRT, camera, power, thermal, or production networking.

## Host and storage contract

- QEMU: `QEMU emulator version 10.0.2`, `virt` machine, TCG acceleration.
- Guest: verified Ubuntu 24.04 minimal ARM64 cloud image whose SHA-256 is pinned
  in `qemu_vm.py`.
- External root: `/Volumes/N1_WORK/giraffe-stage2`; images, guest disks, keys,
  logs, and workspaces remain outside the repository.
- Network fallback: local-only bridge following `bcdYi → AIVAN → Singapore`.
  No bridge address, credential, or public endpoint is committed.

Ubuntu's minimal ARM64 image references separate `BOOT` and `UEFI` labels. The
prepare action therefore creates two standard GPT disks: an ext4 `BOOT`
partition and a FAT32 `UEFI` partition. With the QEMU framework used on the
Stage 2 Mac, both partitions are visible but the image still omits the expected
`/dev/disk/by-label/BOOT` link at the initial mount deadline. The guest therefore
stops in emergency mode before delayed device discovery creates both label
links. `run-probe` continues boot only when the serial log contains the exact
ARM64, BOOT-label, and maintenance-prompt markers; it sends Control-D over a
localhost-only serial channel and records that recovery in the manifest. The
subsequent BOOT and UEFI mounts must succeed. Any other emergency remains
blocked.

## Prepare and start

Set host-local paths without placing secrets in shell history or the repository:

```bash
export STAGE2_ROOT=/Volumes/N1_WORK/giraffe-stage2
export STAGE2_QEMU=/path/to/qemu-system-aarch64
export STAGE2_FIRMWARE=/path/to/edk2-aarch64-code.fd
export STAGE2_QEMU_RESOURCES=/path/to/qemu/resources
```

Prepare the verified image copy, cloud-init seed, SSH key, and GPT support disks:

```bash
.venv/bin/python -m sandbox_tests.stage2.qemu_vm prepare \
  --root "$STAGE2_ROOT"
```

When the approved local bridge is needed for guest package installation, add a
host-local `--guest-https-proxy` value. The retained manifest records only that
a proxy was configured, never credentials.

Start the guest:

```bash
.venv/bin/python -m sandbox_tests.stage2.qemu_vm start \
  --root "$STAGE2_ROOT" \
  --qemu "$STAGE2_QEMU" \
  --firmware "$STAGE2_FIRMWARE" \
  --resource-dir "$STAGE2_QEMU_RESOURCES"
```

## Run the CV probe

```bash
.venv/bin/python -m sandbox_tests.stage2.qemu_vm run-probe \
  --root "$STAGE2_ROOT" \
  --repository . \
  --output sandbox_tests/reports/evidence/stage2/arm64-cv-probe.json \
  --timeout-seconds 5400
```

The probe refuses a guest that does not report `aarch64` or `arm64`. It copies
only test/source directories, performs standalone CV, records dependency
versions, and makes zero camera or LLM/VLM calls.

The 90-minute ceiling accommodates the first Ubuntu package installation under
software TCG. A timeout stops only the host-side waiter; it does not terminate
the guest, and a subsequent probe may resume after confirming cloud-init is
still making progress.

## Evidence handling

- Commit the sanitized VM manifest, selected serial evidence, and generated CV
  probe result only.
- Never commit the guest private key, `known_hosts`, PID file, VM image, support
  disks, package cache, or bridge configuration.
- Treat TCG timings as simulator observations, not performance evidence.
- A failed mount or dependency remains a failed attempt; retain its external
  diagnostic log and rerun from a fresh verified image copy.
