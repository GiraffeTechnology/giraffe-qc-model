# Stage 2 Q1 decision record

Status: **decision required**

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

Record after user confirmation:

- Selected method: **pending**
- ARM/QEMU fidelity required: **pending**
- Selected external volume: **pending**
- Reason for selection: **pending**
- Confirmed by/date: **pending**

UI validation is required for all three choices and follows
`UI_VALIDATION_PLAN.md`.
