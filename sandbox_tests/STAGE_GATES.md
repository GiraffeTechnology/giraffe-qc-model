# Sandbox phased-test gates

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

Only Stage 1 is executable on this branch. Later stages remain deliberately
blocked and are not represented as completed work.

| Gate | Blocks | Required user/product decision | Current state |
|---|---|---|---|
| Q1 | Stage 2 | Container/virtualization (including whether QEMU aarch64 fidelity is required) versus filesystem-level external-drive simulation | Blocked |
| Q2 | Stage 4 | Numeric verdict-consistency threshold and repetition count | Blocked |
| Q3 | Stage 3 | JetPack reflash as a precondition versus an in-stage sub-task | Blocked |
| Q4 | Stage 3 | Fully local Jetson inference, server arbitration, or the Architecture-v2 cloud topology | Blocked |
| Q5 | Stage 4 | Whether Austin's security-baseline review must precede Stage 4 | Blocked |

The Stage 2 branch must not be opened until Stage 1 is merged and its acceptance
checklist is explicitly approved by the user. Stage 3 and Stage 4 follow the same
strict sequential rule.
