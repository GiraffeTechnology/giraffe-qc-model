# Jetson Xavier NX 真实推理 Runtime 可行性调研

**目的：** 回答 Phase 1 测试暴露的核心问题——qc-model 的 VLM 推理能不能在当前
Jetson Xavier NX 测试机上真实跑起来（而非 mock）。仅评估，不实现、不重刷、不
提交任何设备端改动。设备端实测（Phase 1.5）由 Codex 在 `192.168.5.35` 上执行。

## 0. 结论先行

- **在当前固件（JetPack 4.6.1 / CUDA 10.2 / TensorRT 8.2）下，四个候选后端里
  没有一个有官方维护的、面向 CUDA 10.2 + Volta(sm_72) 的生产级支持**——全部要么
  已经放弃 CUDA 10.2，要么从未支持 Xavier 的 Volta 架构。
- **TensorRT-LLM 在任何 JetPack 版本下都不适用于 Xavier NX**：官方 Jetson 分支
  只覆盖 Orin（Ampere, sm_87+），Xavier（Volta, sm_72）不在其内，这与
  JetPack/CUDA 版本无关，是架构层面的硬性排除。
- **升级 JetPack 5.x（CUDA 11.4）后，llama.cpp 和 onnxruntime 有现实可行路径**；
  MNN 的 CUDA 后端在 Jetson/aarch64 上缺乏官方验证证据，即使升级也需设备端实测
  确认，不能默认可行。
- 无论哪个后端，**Python 绑定版本是独立于 CUDA 版本的第二道障碍**：项目 venv 是
  Python 3.11，而 JetPack 4.6.1 系统 Python 是 3.6.9；社区/NVIDIA 预编译 wheel
  普遍只覆盖系统 Python（cp36 或 JetPack 5 的 cp38），没有 cp311 aarch64 +
  CUDA10.2/11.4 的预编译包。这意味着无论选哪个后端，大概率都要么从源码为
  Python 3.11 编译绑定，要么把推理进程做成独立子进程/HTTP 服务（llama.cpp 的
  `llama-server`、MNN 的 C++ CLI 均可如此），由 adapter 通过进程边界调用，从而
  完全绕开 Python ABI 版本问题。**这一点应该写进 2b 的 adapter 设计里。**

## 1. 设备现状约束（实测数据，来自 `PHASE1_BASELINE.md`，2026-07-12 采集）

| 项目 | 实测值 |
|---|---|
| OS | Ubuntu 18.04.6 LTS |
| L4T | R32.7.1 |
| JetPack 家族 | 4.6.1 |
| CUDA runtime | 10.2.300（`nvcc` 不在 PATH） |
| cuDNN | 8.2.1.32 |
| TensorRT | 8.2.1 |
| 系统 Python | 3.6.9 |
| 项目 venv Python | 3.11.15（`.conda311`） |
| GPU | Xavier NX（Volta，384 CUDA cores，48 Tensor Cores），compute capability
  **7.2**（NVIDIA 员工 dusty_nv 在官方论坛用 `deviceQuery` 实测确认，见引用） |
| RAM | **7.6 GB 总量，空闲时可用 5.6 GB**（这是 8GB 版 Xavier NX 模组，不是
  16GB 版；桌面会话已占用约 2GB） |
| 内核 | `Linux 4.9.253-tegra` aarch64 |

这台设备是 **8GB 内存的 Xavier NX**，空闲可用内存只有 5.6GB——这个数字直接约束
第 4 节的模型选型：8B/int4 级别模型的运行时峰值内存必须留出摄像头管线、OS 和
qc-model 服务本身的开销后仍有余量。

## 2. 候选推理后端逐一核对（引用官方文档 / release notes，不凭印象）

### 2.1 llama.cpp（`GGML_CUDA=ON`）

- **CUDA 10.2 + Volta 上曾经能跑，但需要锁定旧 commit + 手工 patch。**
  社区维护的 Jetson 移植（`kreier/llama.cpp-jetson`）文档明确记录：用 CUDA 10.2
  + GCC 8.5 编译特定 commit（`a33e6a0` / build b5050）能跑，但 mainline 之后引入
  的 `bfloat16` 支持依赖 nvcc 10.2 不具备的特性，必须手工打 patch 屏蔽或伪造
  `nv_bfloat16` 类型才能编译过。这是**社区个人验证**，不是项目官方支持声明。
  （[llama.cpp-jetson gist](https://gist.github.com/kreier/6871691130ec3ab907dd2815f9313c5d)）
- **官方维护的容器（`dustynv/llama_cpp`，jetson-containers 项目）已经不覆盖
  JetPack 4 / L4T r32。** Docker Hub 上可见的最早 tag 是 `r35.2.1`（JetPack
  5.x），最新到 `r36.4.x`（JetPack 6）；没有 r32 系列的 tag。
  （[dustynv/llama_cpp tags](https://hub.docker.com/r/dustynv/llama_cpp/tags)）
- jetson-containers 项目当前声明的最低支持版本是 **JetPack 4.6.1+（≥ L4T
  R32.7.1）**，技术上仍在支持范围内，但同一仓库的一个已归档 issue 显示：
  即使是同为 R32.x 系列内的小版本升级（R32.7.1 → R32.7.4），已发布容器就会因
  `libcublas.so.10` / `libcurand.so.10` 缺失而直接跑不起来，说明 R32 系列的
  实际可用性并未被持续验证。
  （[jetson-containers README](https://github.com/dusty-nv/jetson-containers/blob/master/README.md)、
  [issue #261](https://github.com/dusty-nv/jetson-containers/issues/261)）
- **架构层面没有问题**：llama.cpp 默认编译的 `CMAKE_CUDA_ARCHITECTURES` 包含
  `70`（Volta）这一档，Xavier NX 的 sm_72 可以通过 PTX 向前兼容运行 sm_70
  编译产物，所以问题不在算力代际，而在 **CUDA 10.2 工具链本身能否编译当前
  mainline**。
- **结论**：CUDA 10.2 下不是"完全不能跑"，而是"只能跑一个锁定的旧 commit，
  需要手工 patch，且无官方维护，任何后续 bug 都要自己修"——生产不可接受地脆弱。
  升级到 JetPack 5.x（CUDA 11.4）后有官方维护的 jetson-containers 镜像
  （r35.x 系列），是现实可行路径。

### 2.2 MNN（Alibaba，项目已在 Android Pad 端使用同一框架）

- MNN 官方文档确认其 GPU 加速路径是"CUDA + Tensor Core 用于服务器/桌面 GPU，
  Metal/OpenCL/Vulkan 用于移动端"（[alibaba/MNN README](https://github.com/alibaba/MNN)）。
  **没有找到 MNN 官方文档明确声明 CUDA 后端在 aarch64/Jetson 上被测试或支持**——
  `MNN_CUDA=ON` 的编译选项存在，但官方编译文档（`docs/compile/engine.md`）
  未列出所需 CUDA 版本、目标算力代际，也未提及 ARM/aarch64/Jetson 平台。
  这与项目现有 Android 端使用的 MNN 后端（CPU/OpenCL，非 CUDA）是不同的代码路径，
  **不能因为项目已用 MNN 就默认它在 Jetson 上的 CUDA 后端可行**。
- 该社区 issue（[alibaba/MNN#825](https://github.com/alibaba/MNN/issues/825)）
  只有用户提问、无官方回复内容可引用，未能确认 Jetson 兼容性。
- **结论**：MNN 在 Jetson 上继续走 CPU 路径（已知能跑，但 8B 级模型 CPU 推理
  在 Xavier NX 上的延迟不可接受）是唯一有证据支撑的路径；CUDA 后端在
  aarch64/Jetson/CUDA10.2-11.4 上是否可行**没有可引用的官方或社区证据**，
  必须作为设备端验证项，不能纳入当前可行性结论。

### 2.3 TensorRT-LLM

- 官方支持矩阵明确写出：**最低 GPU 架构 SM80（Ampere）**，最低 **TensorRT
  10.11**，仅支持 Linux x86_64 / aarch64（数据中心 SBSA，非 Tegra 嵌入式变体）。
  （[TensorRT-LLM Support Matrix](https://nvidia.github.io/TensorRT-LLM/reference/support-matrix.html)）
- 官方为 Jetson 单独维护了一个分支（`v0.12.0-jetson`），但**只覆盖 Jetson AGX
  Orin（JetPack 6.1，Ampere sm_87）**，不含 Xavier。
  （[NVIDIA 论坛帖](https://forums.developer.nvidia.com/t/tensorrt-llm-for-jetson/313227)）
- **结论：与 JetPack/CUDA 版本无关的硬性排除。** Xavier NX 的 GPU 是 Volta
  sm_72，无论升不升级 JetPack，都达不到 TensorRT-LLM 要求的 sm_80。**此选项
  彻底排除，不需要再评估。**

### 2.4 onnxruntime（CUDA Execution Provider）

- 官方文档给出的历史版本表：**ONNX Runtime 1.5–1.6 是最后支持 CUDA 10.2 的版本
  （需配 cuDNN 8.0.3）**；当前 ORT 要求 CUDA 12.x + cuDNN 9（1.19+ 默认发布
  CUDA12 包，1.22 起只发布 CUDA12 包）。
  （[ONNX Runtime CUDA EP 文档](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)）
- 设备实测 cuDNN 是 8.2.1.32，与 ORT 1.5-1.6 要求的 8.0.3 不完全一致（次版本
  差异，历史上 onnxruntime 对 cuDNN 8.x 内的次版本通常兼容，但未见官方对
  8.2.1 的明确背书，需设备端验证）。
- NVIDIA Jetson Zoo 历史上发布过 JetPack 4.6 对应的 onnxruntime-gpu 预编译
  wheel（如 `onnxruntime_gpu-1.10.0-cp36-cp36m-linux_aarch64.whl`），但
  **wheel 是为系统 Python 3.6（cp36）编译的**，项目用 Python 3.11——需要
  从源码为 cp311 重新编译，且 1.10.0 版本实际使用的是否仍是 CUDA10.2 工具链
  需要与 Jetson Zoo 发布记录逐条核对（未在本次调研中逐一验证到版本级 CUDA
  绑定，标记为设备端待确认项）。
  （[Jetson Zoo ONNX Runtime 公告](https://developer.nvidia.com/blog/announcing-onnx-runtime-for-jetson/)）
- **结论**：CUDA10.2 下技术上有过官方支持的先例（ORT 1.5-1.6 时代），但版本
  太老、且 Python 绑定要为 cp311 重新编译，工程成本高、收益（老版本 ORT 的
  VLM/transformer 算子覆盖率）存疑。升级 JetPack 5.x 后能用近期 ORT 版本
  （仍需确认 CUDA11.4 与 ORT 要求的 CUDA11.8/12.x 是否兼容，见第 3 节前提），
  是比 CUDA10.2 路径更现实的选项。

### 2.5 额外补充：原生 TensorRT 8.2（不经过上层框架，设备已安装）

设备上已经有 TensorRT 8.2.1，不需要新增运行时依赖。理论上可以把 VLM 的视觉
encoder（或整个模型，若结构允许）转成 ONNX 再手工构建 TensorRT engine。但
TensorRT 8.2 对 Transformer/attention 结构缺乏 TensorRT-LLM 那样的原生优化和
KV-cache 管理，8B 级别的 decoder-only VLM 要在 TRT 8.2 上手工搭建等价于重新
实现一遍 TensorRT-LLM 已经做的工作，工程量和长期维护成本都远超前面几个选项，
**不建议作为首选**，仅记录在案供人工在选型阶段参考。

## 3. 若必须升级 JetPack 5.x：影响评估（仅评估，不执行——重刷是人工批准事项）

### 3.1 硬性事实

- **JetPack 4.x → 5.x 没有原地升级路径。** 5.x 对应 L4T r35（Ubuntu 20.04），
  bootloader 与 4.x（L4T r32，Ubuntu 18.04）不兼容，只能整机重刷。
  （[JetsonHacks: Upgrade Xavier NX to JetPack 5](https://jetsonhacks.com/2022/11/03/upgrade-jetson-xavier-nx-to-jetpack-5/)）
- Xavier 系列（AGX Xavier / Xavier NX）的官方支持上限是 **JetPack 5.1.x**——
  JetPack 6 已经放弃 Xavier，只支持 Orin 系列。
  （[JetPack/L4T 兼容表](https://proventusnova.com/blog/jetpack-versions-l4t-compatibility-table/)）
- 重刷用 SDK Manager，需要一台运行 Ubuntu 18.04/20.04 的 x86 主机，通过
  USB 把 Jetson 拉进 recovery 模式刷写；**QSPI bootloader 刷写过程中断电/
  连接中断可能导致设备变砖，需要重新走恢复流程。**
- JetPack 5.x 下 CUDA 变为 **11.4**，cuDNN/TensorRT 版本随之整体上移
  （对应 TensorRT 8.5/8.6 系列），这是本次评估把"JetPack5.x = CUDA11.4"作为
  前提的依据。

### 3.2 数据备份清单（重刷前必须完成，人工执行）

- `/home/giraffe/work/giraffe-qc-model` 整个仓库工作区（`git status` 确认
  clean 后仍建议整目录打包，因为可能有未追踪的本地产物/日志）。
- `/home/giraffe/work/qwen3-vl-2b-mnn` 模型资产目录（重新下载成本取决于
  网络，量级是 GB 级，见第 1 节 P0 规则：只能用 Jetson 自己的 Wi-Fi 下载）。
- `data/jetson/` 下的本地 SQLite 数据库（Phase 1 测试数据，如果有留存价值）。
- `artifacts/jetson_photo_smoke/`、`artifacts/jetson_pad_server_loop/` 等
  测试产出目录，如果需要留存对比基线。
- 现有 systemd/服务配置（`PHASE1_BASELINE.md` 记录的 `/etc/systemd/system/*.service`
  文件 SHA-256），重刷后需要重新安装。
- SSH host key / `known_hosts` 记录，重刷后 host key 会变化，操作端需要更新。
- 网络配置（Wi-Fi SSID/密码，`nmcli` 连接 profile），重刷后 Wi-Fi 需要重新配置
  才能满足"Jetson 自己下载"的 P0 规则。

### 3.3 刷机步骤概述（人工执行，不在本次调研中操作设备）

1. 在 x86 主机（Ubuntu 18.04/20.04）安装 NVIDIA SDK Manager。
2. Jetson Xavier NX 进入 Force Recovery 模式（短接/按键组合，随载板型号而定），
   USB 连接主机。
3. SDK Manager 选择 JetPack 5.1.x，刷写 L4T root filesystem + 可选组件
   （CUDA/cuDNN/TensorRT/OpenCV）。
4. 首次开机走 Ubuntu 20.04 out-of-box 设置（用户/网络）。
5. 按 `docs/jetson-xavier-nx-test-deployment.md` 现有流程重建 Python 3.11
   venv、拉取仓库、恢复 SSH 访问、重新配置 Wi-Fi。
6. 重新走一遍 Phase 1 baseline 采集（复用 Codex 已用的采集脚本/清单），确认
   新固件下 CUDA/cuDNN/TensorRT 版本符合预期。

### 3.4 风险

- **变砖风险**：QSPI 阶段断电/连接中断可恢复但需要重新走完整刷机流程，期间
  设备完全不可用。
- **不可逆**：升级后无法用重刷以外的方式回退到 JetPack 4.x；如果 5.1.x 上
  出现未预料的兼容问题（性能倒退、驱动问题），回退同样需要整机重刷。
  （已有社区报告过 Xavier NX 升级到 JetPack5 后出现性能问题的案例，
  [NVIDIA 论坛](https://forums.developer.nvidia.com/t/performance-issues-when-upgrading-to-jetpack-5/308415)，
  说明升级本身有已知的现实风险，不是纯理论担忧。）
- **停机时间**：整个流程（含数据恢复、环境重建）预计以小时计，具体取决于
  操作熟练度和网络下载模型资产的耗时；Phase 1 baseline 显示模型资产在 GB 级，
  P0 规则要求只能用 Jetson 自己的 Wi-Fi 下载，会拉长恢复时间。
- **系统 Python 版本也会变**（JetPack 5.x 系统 Python 通常是 3.8），如果未来
  任何环节意外依赖系统 Python（目前项目严格使用独立的 `.conda311`，理论上
  不受影响，但升级后应重新确认这条边界没有被破坏）。

## 4. 可行组合选项（供人工选型，非最终决定）

以下每个组合都标注了内存占用数据的**来源**，不臆造数字；标"待设备实测"的项
是本次调研找不到可直接引用的公开数据，需要 Phase 1.5 在真实设备上测量。

### 选项 A —— 不重刷，维持 JetPack 4.6.1 / CUDA 10.2，llama.cpp 锁定旧 commit

- **模型变体**：与现有 tablet 端一致量级的小模型（2B 级，INT4/Q4），而非
  server 端的 8B 档——CUDA10.2 下的 llama.cpp 分支未经性能验证，选小模型
  降低失败面。
- **推理后端**：llama.cpp，锁定 `kreier/llama.cpp-jetson` 验证过的 commit
  （`a33e6a0` 附近），手工 patch bfloat16 问题后自行编译；adapter 通过子进程/
  `llama-server` HTTP 接口调用，规避 Python 3.11 绑定问题。
- **是否需重刷**：否。
- **预期内存占用**：项目自己的 `docs/DEPLOYMENT_LOCAL_QWEN.md` 记录 Android
  端 Qwen2-VL-2B-Instruct-MNN INT4 运行时约需 **3–4 GB**，峰值预算
  ≤ **6 GB**（同量级模型在 llama.cpp GGUF INT4 下的量级预期接近，但不同
  runtime 的 KV-cache/激活值开销不同，需设备实测校准）。设备空闲可用内存
  只有 5.6GB（第 1 节），意味着这个选项的内存余量**很紧**，几乎没有给
  OS/摄像头管线/qc-model 服务本身留缓冲，需要设备端实测确认，不能只凭
  换算数字下结论。
- **风险**：无官方维护，是本次调研里工程和维护风险最高的组合，仅建议作为
  "完全不能重刷"前提下的兜底方案。

### 选项 B —— 重刷 JetPack 5.1.x（CUDA 11.4），llama.cpp（jetson-containers 官方镜像）

- **模型变体**：可以尝试 server 档 `qwen3.5-vl-8b-int4`（当前 server 端默认
  profile，见 `src/qc_model/runtime_profiles.py`），但需先用第 1 节确认的
  8GB 内存上限核对可行性。
- **推理后端**：llama.cpp，走 `dustynv/llama_cpp` 官方维护的 `r35.x` 系列
  容器（jetson-containers 项目积极维护 JetPack 5.x），有官方 CI/发布支撑，
  不需要手工 patch。
- **是否需重刷**：是（JetPack 4→5，见第 3 节）。
- **预期内存占用**：Qwen3-VL-8B-Instruct 量化到 INT4 后**权重本身约 4.8GB**
  （Spheron GPU 推荐工具给出的量化后 VRAM 数据），但**这只是权重，不含
  KV-cache/激活值**——同一模型 Q4_K_M 量级在另一数据源里给出约 **12GB**
  的总占用估算（含上下文/激活开销）。这两个数字差距很大，说明 8B 档在
  8GB 内存的 Xavier NX 上**大概率装不下**，需要用更短的上下文窗口/更激进
  的 KV-cache 策略重新估算，或直接降级到更小模型（见选项 C）。
  （[Qwen3-VL-8B-Instruct VRAM 数据](https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen3-VL-8B-Instruct/)）
- **风险**：重刷本身的风险见第 3.4 节；内存是否够用是本选项最大的不确定项，
  必须设备端实测，不能假设可行。

### 选项 C —— 重刷 JetPack 5.1.x（CUDA 11.4），2B 档模型 + onnxruntime 或 llama.cpp

- **模型变体**：`qwen3.5-vl-2b-mnn` 同量级的 2B 档 INT4 模型（复用 tablet
  端已验证过内存预算的模型规模，而不是 server 端的 8B），用 GGUF/ONNX 格式
  重新导出以匹配所选 runtime。
- **推理后端**：onnxruntime CUDA EP（需要为 cp311 + CUDA11.4 重新编译，
  较新版本 ORT 官方主线是 CUDA12，需确认某个中间版本对 CUDA11.4 的兼容窗口）
  或 llama.cpp（同选项 B 的官方容器路径，只是换成 2B GGUF）。
- **是否需重刷**：是。
- **预期内存占用**：参照第 1 节引用的项目自有数据——2B INT4 在移动端 MNN
  runtime 下实测预算是 3–4GB（峰值 ≤6GB）。这与 8GB 设备的 5.6GB 空闲内存
  比选项 B 更匹配，是**内存风险最低**的组合，代价是模型能力弱于 8B 档
  server profile，需要在选型时权衡准确率。
- **风险**：重刷风险同上；onnxruntime 版本与 CUDA11.4 的精确兼容窗口本次
  调研未逐版本核实，需要设备端建 venv 实测确认能装上正确的 wheel/编译成功。

## 5. 未决问题（需要 Phase 1.5 设备端验证，不能靠调研拍板）

1. MNN 的 `MNN_CUDA=ON` 后端在 aarch64 + CUDA10.2/11.4 上能否编译、能否跑
   ——本次调研没有找到可引用的官方或社区证据，是全部选项里证据最薄弱的一项。
2. onnxruntime 某个具体版本对 CUDA 11.4（而非官方主推的 11.8/12.x）的兼容
   窗口，需要在实际 JetPack 5.1.x 环境里 `pip install` / 源码编译验证。
3. 选项 B（8B 档）在 8GB 物理内存上的真实峰值占用——4.8GB 权重 vs 12GB
   总量两个数据源差距很大，必须设备实测 KV-cache/激活值开销后才能下结论，
   不能假设可行。
4. llama.cpp 选项 A 锁定 commit 的 patch 在这台设备的具体 GCC/glibc 版本
   组合下是否真的能编译通过——社区记录是另一台 Jetson Nano（不同 SoC/
   glibc），不是 Xavier NX 本机验证。

---

引用来源汇总（按首次出现顺序）：

- [llama.cpp CUDA10.2 + Volta Jetson 移植记录](https://gist.github.com/kreier/6871691130ec3ab907dd2815f9313c5d)
- [dustynv/llama_cpp 官方容器 tag 列表](https://hub.docker.com/r/dustynv/llama_cpp/tags)
- [jetson-containers README（支持版本声明）](https://github.com/dusty-nv/jetson-containers/blob/master/README.md)
- [jetson-containers issue #261（R32 系列小版本兼容性问题）](https://github.com/dusty-nv/jetson-containers/issues/261)
- [alibaba/MNN README（CUDA/Tensor Core 说明）](https://github.com/alibaba/MNN)
- [alibaba/MNN issue #825（CUDA 支持提问，无官方结论）](https://github.com/alibaba/MNN/issues/825)
- [TensorRT-LLM Support Matrix（SM80 最低要求）](https://nvidia.github.io/TensorRT-LLM/reference/support-matrix.html)
- [NVIDIA 开发者论坛：TensorRT-LLM for Jetson（仅 Orin 分支）](https://forums.developer.nvidia.com/t/tensorrt-llm-for-jetson/313227)
- [ONNX Runtime CUDA Execution Provider 文档（历史版本表）](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [NVIDIA Jetson Zoo ONNX Runtime 公告](https://developer.nvidia.com/blog/announcing-onnx-runtime-for-jetson/)
- [JetsonHacks：Xavier NX 升级 JetPack5 步骤](https://jetsonhacks.com/2022/11/03/upgrade-jetson-xavier-nx-to-jetpack-5/)
- [JetPack/L4T 兼容性对照表（Xavier 系列支持上限 5.1.x）](https://proventusnova.com/blog/jetpack-versions-l4t-compatibility-table/)
- [NVIDIA 开发者论坛：Xavier NX 升级 JetPack5 后性能问题案例](https://forums.developer.nvidia.com/t/performance-issues-when-upgrading-to-jetpack-5/308415)
- [NVIDIA 开发者论坛：dusty_nv 实测 Xavier NX compute capability 7.2](https://forums.developer.nvidia.com/t/what-compute-capability-of-jetson-xavier-nx-gpu-is/146241/4)
- [Qwen3-VL-8B-Instruct INT4 VRAM 估算（Spheron GPU 推荐工具）](https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen3-VL-8B-Instruct/)
