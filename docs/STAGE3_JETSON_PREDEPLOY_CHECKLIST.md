# Stage 3 Jetson 真机部署准备清单

基线:拉取评审通过的最新 `main`。**不要在本文档硬编码具体 commit** ——
`scripts/jetson_stage3_predeploy_check.py` 会在真机上通过 `git rev-parse
HEAD` 自动把实际部署的 commit 写入就绪自检证据(`deployed_commit` 字段),
这是唯一应被信任的"当前部署基线是哪个 commit"的记录来源,长期文档里的
硬编码提交号会在下一次合并后立刻过期且无法自我校验。

## 0. 授权边界(先读)

Stage 2 修复记录(2026-07-22)明确:**只有全新的 Stage 2 交互验收通过后,
才恢复 Stage 2 通过状态并授权 Stage 3 Jetson A/B 测试**。本清单覆盖的是
"部署准备"——刷机、装依赖、建服务、跑就绪自检——这些可以与 Stage 2
重验收并行推进;但 Stage 3 的正式测试开始前,Stage 2 重验收必须先完成,
且 `sandbox_tests/prd_traceability.json` 中相应条目要引用真实验收工件。

## 1. 真机准备(人工执行,不可由 CI 代替)

按 `docs/JETSON_PRODUCTION_DEPLOYMENT_RUNBOOK.md` §1–§2:

- [ ] 备份并记录设备序列号、当前镜像摘要、网络配置
- [ ] 用 SDK Manager + Force Recovery 重刷认可的 JetPack 镜像,保留完整
      刷机日志
- [ ] 记录 JetPack/L4T、CUDA、cuDNN、TensorRT 版本与散热基线
- [ ] 团队填齐并批准 `deploy/jetson/mnn-sdk.lock.json`(GAP-03:
      source_url/git_commit/sha256/build_flags/target_arch/jetpack_version/
      l4t_version,`approved: true`),然后校验:
      `python3 scripts/jetson_verify_mnn_lock.py --archive <已下载的 SDK 归档>`
      —— 不通过就不得继续构建
- [ ] 安装钉版 MNN SDK,记录版本/摘要(与已批准的 lock 一致)
- [ ] 基于 `deploy/jetson/model-manifest.example.json` 为每个 Group A 模型
      选择(2B / 4B 各自独立)填写 `model_manifest.json`,记录模型名、修订、
      每个文件的 SHA-256、量化方式(`qwen3-vl-4b` 是可替换默认,非产品身份),
      然后校验:
      `python3 scripts/jetson_verify_model_manifest.py --manifest <path>/model_manifest.json --mnn-lock deploy/jetson/mnn-sdk.lock.json`
      —— 不通过就不得把该模型标记为可用
- [ ] 构建 native bridge:
      `cmake -S jetson_runner/native -B build/xavier-mnn -DMNN_ROOT=/opt/mnn-pinned && cmake --build build/xavier-mnn --config Release`
- [ ] 安装 `libgiraffe_mnn_bridge.so` 到配置路径

## 2. 服务安装(本仓库新增部署件)

- [ ] 拉取评审通过的最新 `main` 到 `/opt/giraffe/giraffe-qc-model`,建 venv
      并安装 `jetson_runner/requirements.txt`
- [ ] 复制 `deploy/jetson/xavier-admin-runner.env.example` →
      `/etc/giraffe/xavier-admin-runner.env`(mode 640),填齐所有占位符;
      `XAVIER_HARDWARE_VALIDATION_STATUS` 保持 `not_run`
- [ ] 安装 systemd 单元 `deploy/jetson/giraffe-xavier-admin-runner.service`,
      `systemctl enable --now`
- [ ] 确认 mock 拒绝:临时把 `XAVIER_INFERENCE_MODE` 改为 `mock` 重启一次,
      服务必须拒绝启动(`MockModeNotAllowedInProduction`),然后改回 `real`
- [ ] 非回环访问必须有 TLS 终结(反向代理)

## 2.5 Group B 远程隧道(如需在部署准备阶段一并配置)

按 `docs/STAGE3_GROUP_B_REMOTE_ADAPTER.md`:

- [ ] 在远程主机为专用 SSH key 配置受限 `authorized_keys`(`command="/bin/false"`
      + `permitopen` 限定到远程服务自身回环端口)
- [ ] 复制 `deploy/jetson/stage3-group-b-tunnel.env.example` →
      `/etc/giraffe/stage3-group-b-tunnel.env`(mode 640),填齐占位符
- [ ] 安装 systemd 单元 `deploy/jetson/giraffe-stage3-group-b-tunnel.service`,
      `systemctl enable --now`
- [ ] 确认隧道自动重连(重启远程 sshd 或短暂断网后应自动恢复)
- [ ] `RemoteChatVlmInspectionProvider` 的 `VLM_BASE_URL` 只指向本机转发端口
      (`127.0.0.1:<local port>`),不得直接指向远程主机地址

## 3. 就绪自检(真机上执行)

```bash
XAVIER_CHECK_BEARER=<admin bearer> \
python3 scripts/jetson_stage3_predeploy_check.py \
    --base-url http://127.0.0.1:8600 \
    --output /opt/giraffe/evidence/stage3_predeploy_check.json
```

- [ ] 全部检查 PASS(production 环境、real 模式、bridge/模型在盘、livez、
      签名 health、`model_loaded=true`)
- [ ] 自检 JSON 存档(它只是就绪观察,不是验收证据,不能翻
      hardware_validation 状态)

## 4. 硬件验证门(Stage 3 测试的前置)

按 `jetson_runner/HARDWARE_VALIDATION.md` 完整执行并留证:签名 health
前后对照、无效签名/重放/摘要不符/缺模型/过热路径、金样本图全流程原始
输出、5 次连续真实工作流、断电重启恢复。只有评审过的不可变证据才允许把
`XAVIER_HARDWARE_VALIDATION_STATUS` 置为 `passed` 并给出
`XAVIER_HARDWARE_VALIDATION_EVIDENCE_REF`。

## 5. 正式 Stage 3 A/B 测试(单独授权门禁)

部署准备完成不等于可以开始正式测试。执行前先确认:

```bash
python3 scripts/ci/stage3_authorization_gate.py
```

门禁 CLOSED 时,`scripts/jetson_stage3_run_group_a.py` /
`jetson_stage3_run_group_b.py` 会自行拒绝运行,不产生任何报告——不存在
绕过参数。门禁只在 `sandbox_tests/prd_traceability.json` 的 `PRD-S2-30`
指向一份真实存在、`passed`、非 mock、足够新的 Stage 2 报告时才会 OPEN。

## 6. 证据回填

- [ ] 把硬件验证证据引用回填进 `sandbox_tests/prd_traceability.json`
      (PRD-S2-20 Jetson 硬件加速行),由 PRD traceability 门禁校验其存在
- [ ] Stage 3 A/B 测试报告落地为
      `sandbox_tests/reports/stage3_ab_<group>_<timestamp>.json`,符合
      `sandbox_tests/reports/stage3_ab_report.schema.json`;
      `scripts/ci/stage3_ab_report_check.py` 与
      `scripts/ci/report_evidence_check.py` 会拒绝零真实调用或字段缺失的
      `passed` 声明
