# Sandbox phased-test gates

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

Stage 1 is accepted and merged. Stage 2 has its own branch and gate-ready
scaffold; simulator installation/execution remains blocked on Q1. Later stages
remain deliberately blocked and are not represented as completed work.

| Gate | Blocks | Required user/product decision | Current state |
|---|---|---|---|
| Q1 | Stage 2 execution | QEMU aarch64, native container, or filesystem-level external-drive simulation; also select the target external volume | Decision required; scaffold and UI plan ready |
| Q2 | Stage 4 | Numeric verdict-consistency threshold and repetition count | Blocked |
| Q3 | Stage 3 | JetPack reflash as a precondition versus an in-stage sub-task | Blocked |
| Q4 | Stage 3 | Fully local Jetson inference, server arbitration, or the Architecture-v2 cloud topology | Blocked |
| Q5 | Stage 4 | Whether Austin's security-baseline review must precede Stage 4 | Blocked |

The Stage 2 branch was opened only after Stage 1 merged and its acceptance report
passed. Stage 3 and Stage 4 follow the same strict sequential rule.
