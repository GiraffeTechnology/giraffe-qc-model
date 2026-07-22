# Stage 3 Jetson 测试规格(权威定义)

本文件是 Stage 3 真机测试的唯一权威定义来源。后续实现、脚本、报告和文档
必须使用本文件的 Group A 定义,**不得**复用仓库中历史的
`scripts/run_capability_a_demo.py` / `run_capability_b_demo.py`("Capability
A/B")命名或结论 —— 那两个脚本是与本规格无关的历史能力演示(见下文
「与历史 Capability A/B 的关系」),不构成 Stage 3 证据。

## 0. Group B 已停用(生产决策,2026-07-22)

远程/云端 VLM(原 Group B:Jetson CV + 远程 Qwen3-VL-4B-INT4 服务)已从
生产系统中移除,不再参与 Stage 2 及以后的测试或生产部署。生产级视觉模型
统一为 Jetson/服务器本机运行的 Qwen3-VL-4B,职责收窄为计数确认与明显瑕疵
识别(见 `src/qc_model/studio/ai_gateway.py`)。原 Group B 的远程 adapter
(`remote_chat_provider.py`)、其 Jetson 真机 harness
(`jetson_stage3_run_group_b.py`)、SSH 隧道部署件和相关文档
(`docs/STAGE3_GROUP_B_REMOTE_ADAPTER.md`)已删除。本文件下述条款中提及
"Group B" 之处均为历史记录,仅用于说明规格演进,不代表当前系统仍支持该
路径。`sandbox_tests/reports/stage3_ab_report.schema.json` 的
`stage3_group` 字段已收紧为只接受 `"A"`。

## 1. Group A

```text
Jetson CV + Jetson 本机 Qwen3-VL-2B(或经批准的 4B)MNN → 初筛
```

要求:

- CV 和 VLM 都在 Jetson 本机执行。
- 模型必须是明确选择、钉版、带摘要并可在 Xavier NX 上运行的 MNN 导出包
  (见 `deploy/jetson/mnn-sdk.lock.json` 与模型 manifest,§3)。
- 必须记录实际模型名、修订、量化方式、文件摘要、MNN SDK 版本/commit、
  构建参数和运行 backend。
- 2B 与 4B 不得在未记录的情况下自动切换;若都支持,必须作为两个明确配置
  或两个独立测试矩阵项(`stage3_group=A` 报告的 `model.name` 字段区分)。

## 2. 与历史 Capability A/B 的关系

`scripts/run_capability_a_demo.py`(单图 QC 演示)和
`scripts/run_capability_b_demo.py`(三层视频管线演示)是仓库更早期的能力
演示脚本,与本文件定义的 Group A **没有关系**。两个脚本已在文件头加入
历史标注,禁止把它们的输出当作本规格的 Stage 3 证据。

Stage 3 的真机入口是:

- `scripts/jetson_stage3_run_group_a.py`

启动时调用 `scripts/ci/stage3_authorization_gate.py --require-open`;
Stage 2 重验收门未通过时直接拒绝运行,不产生任何报告。

## 3. 报告 schema

Stage 3 报告必须符合 `sandbox_tests/reports/stage3_ab_report.schema.json`,
在基础报告字段之外强制要求:

| 字段 | 说明 |
|---|---|
| `stage3_group` | `"A"`(唯一有效值) |
| `cv_execution_location` | 恒为 `"jetson_local"` |
| `vlm_execution_location` | 恒为 `"jetson_local"` |
| `model.provider` / `model.name` / `model.revision` / `model.quantization` / `model.backend` | 实际加载的模型身份,不得留空、不得是占位符 |
| `model.manifest_sha256` | 对应模型 manifest 的摘要(见 §模型资产) |
| `call_evidence` | 每个 case 至少一次真实模型调用的原始请求/响应引用(而非重述) |

`scripts/ci/report_evidence_check.py` 沿用既有规则:stage ≥ 2 的
`passed` 报告必须 `model_call_count > 0` 且非全 mock;Stage 3 报告
额外经 `scripts/ci/stage3_ab_report_check.py` 校验上表字段存在且非空。

## 4. 最低验收标准(照抄审计结论,作为本规格的验收清单)

1. 文档中的定义与本文件第 1 节完全一致。
2. 新增的 Stage 3 入口不复用旧 Capability A/B 的含义。
3. MNN SDK 和模型均有不可变版本与 SHA-256。
4. 真实加载模型,`model_loaded=true` 不能由文件存在推断。
5. 记录真实 provider、model、revision、quantization 和 backend。
6. CPU backend 如实报告,不得称为 GPU 加速。
7. Stage 2 新交互验收工件已通过并回填 `sandbox_tests/prd_traceability.json`
   的 `PRD-S2-30`,才允许开始正式 Stage 3 测试
   (`scripts/ci/stage3_authorization_gate.py` 校验)。
8. CI 通过只能证明代码/契约,不得把硬件验证状态改为 `passed`。
9. 所有真机报告保持 `production_eligible=false` 或硬件门状态 `not_run`,
   直到完整硬件验证证据经评审。

## 5. 禁止事项

- 禁止把旧 Capability A/B 报告当作本次 Stage 3 证据。
- 禁止自行选择未批准的 MNN 或模型版本。
- 禁止使用 `latest` 或无摘要模型资产。
- 禁止把 CPU backend 写成 GPU 加速。
- 禁止以 CI、文件存在或服务进程存在代替真实模型推理证据。
- 禁止在 Stage 2 重验收通过前开始正式 Stage 3 测试。
- 禁止重新引入远程/云端 VLM 推理路径作为生产候选,除非有新的、经用户
  明确批准的产品决策推翻 §0 的停用决定。
- 禁止在仓库任何文档、脚本、报告或 PR 描述中写入真实设备主机名、内部
  LAN 地址或其他敏感部署身份信息;引用时使用占位符,实际值只存在于
  不受版本控制的本地部署凭据/环境文件中。
