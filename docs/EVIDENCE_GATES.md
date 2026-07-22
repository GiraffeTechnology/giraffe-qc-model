# Evidence Gates — 测试通过 ≠ PRD 交付

背景:Stage 2 差距审计(2026-07-22)确认了一个反复出现的失败模式——
mock 实现 + 绿色单测被当作"功能已交付",而真实产品链路并未完成。
以下门禁把这两个概念在 CI 机制上解耦。

## 1. PRD 追踪矩阵(硬门禁)

`sandbox_tests/prd_traceability.json` 是差距审计 §3 对照矩阵的机读版本,
由 `scripts/ci/prd_traceability_check.py` 在每次 push/PR 上强制校验:

- 每条 PRD 要求必须声明状态:`verified` / `implemented_unverified` /
  `partial` / `missing`;
- `verified` 必须给出**存在的** `code_evidence` 与 `test_evidence` 路径;
- `requires_real_run: true` 的要求,只有在 `real_run_evidence` 指向仓库中
  真实存在的验收工件(报告/日志)时才允许 `verified` ——
  **绿色单测永远不能把一条真实链路要求翻成已验证**;
- 非 `verified` 条目必须写明 `gap`,缺口不允许隐身。

要把一条 `implemented_unverified` 翻成 `verified`,提交里必须同时带上
新的真实验收工件并在矩阵中引用它,否则 CI 红。

## 2. 报告证据校验(硬门禁)

`scripts/ci/report_evidence_check.py` 校验 `sandbox_tests/reports/*.json`:

- `status` 只能取 schema 允许值;`passed` 是唯一的验收声明;
- Stage ≥ 2 的 `passed` 报告必须有 `summary.model_call_count > 0`,
  且不允许所有 case 都是 `mock_flag: true` ——
  **零次真实模型调用的报告永远不能宣布通过**(审计 §4 的
  `model_call_count: 0` 却 `passed_for_stage3_entry` 事故不可再发生);
- 任何 stage3 准入 acceptance 标志为 true 时,报告本身必须满足上述条件。

## 3. 生产环境 mock 拒绝启动(fail-closed)

mock 不再可能"默默冒充生产":

- Jetson runner:`JETSON_MOCK_MODE`/`XAVIER_INFERENCE_MODE` 在
  `APP_ENV=production` 下选择 mock 会抛
  `MockModeNotAllowedInProduction`(已有);
- Edge CV agent:`edge_cv_agent/app/config.py` 同样拒绝——
  `APP_ENV=production` 下必须显式 `EDGE_AGENT_MOCK_MODE=false`,
  默认的 mock 模式直接拒绝启动;
- 服务端假 provider 仅在显式测试模式可用(已有,
  `test_no_fake_provider_in_prod`)。

## 4. 预设工作流服务端强制(fail-closed)

Stage 2 预设工作流不再是"约定",而是服务端行为:

- **检查点结果带来源**:`qc_checkpoint_results.review_source`
  (`operator` / `model`)与 `reviewed_by`(迁移 026)。操作员经
  `/api/v1/pad/.../checkpoint-results` 提交的结果记为 `operator` 并记录
  复核人;`ingest_model_output` 派生及 finalize 自动补的结果记为 `model`。
- **模型永远不能自证 pass**:Pad 工作流的 finalize 以
  `require_human_review=True` 调用——任何检查点缺少人工复核结果时,
  判定封顶 `review_required`,并在报告中列出未复核的检查点。
  v1 机器 API 路径保持原策略(其人工把关在 L2 human-final 层)。
- **工作流步骤可审计**:`GET /api/v1/pad/inspection-jobs/{id}/workflow`
  按预设顺序(标准激活 → 证据附加 → CV/VLM 分析 → 操作员逐点复核 →
  服务端 finalize)返回每一步的完成状态与 `next_step`,
  跳步不再是不可见的。

## 与既有检查的关系

- `mock_labeling_lint.py`(§1.3,硬):要求 mock 显式标注 —— 管"诚实标注";
- `claims_lint.py`(§1.4,软):文档声明需邻近证据 —— 管"文案不吹牛";
- 本文的三个门禁管"**声明状态必须有可验证的工件支撑**"。

三层合在一起:mock 必须标注、文案必须给证据、状态翻转必须带真实验收工件。
