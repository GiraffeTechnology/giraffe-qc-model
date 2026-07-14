# Stage 2 Q1 decision record

Status: **confirmed**

Choose exactly one method before execution:

1. `qemu_aarch64` — Linux aarch64 container/VM under QEMU. Highest instruction-set
   fidelity of the software-only choices; slower and still not Jetson GPU, CUDA,
   camera, power, or thermal emulation.
2. `native_container` — Linux container on the Mac host architecture. Faster and
   useful for dependency/filesystem isolation, but it cannot reveal x86-to-ARM
   instruction-set incompatibilities.
3. `filesystem_level` — external drive supplies an isolated Jetson-like directory
   and dependency layout while macOS remains the execution host. Best for mount,
   permission, and packaging checks; weakest architecture fidelity.

- Selected method: **`qemu_aarch64`**
- ARM/QEMU fidelity required: **yes**
- Selected external volume: **`N1_WORK`**
- Dedicated root: **`/Volumes/N1_WORK/giraffe-stage2`**
- Reason for selection: exercise the Linux aarch64 instruction set and dependency
  path before Stage 3 while keeping VM images, workspaces, and evidence on the
  selected external volume.
- Confirmed by/date: **user, 2026-07-15 (Asia/Hong_Kong)**

The host is an Intel Mac running macOS 12, so QEMU uses software translation.
The guest must report `aarch64`/`arm64`; an x86 container does not satisfy this
decision.

## Limitations

QEMU `virt` is not a Jetson Xavier NX hardware model. It does not validate the
Jetson GPU, CUDA/TensorRT/MNN acceleration, CSI/USB camera capture, power draw,
thermal throttling, JetPack kernel/device-tree behavior, or production network
topology. Timing is simulator-only and cannot be used as real-hardware or
production performance evidence. These items remain Stage 3 checks.

UI validation is required for all three choices and follows
`UI_VALIDATION_PLAN.md`.
