# TEST_MAP — giraffe-qc-model 代码勘察结果

> 分支基线：`claude/new-session-qcgn1p`  
> 勘察日期：2026-06-26  
> 测试分支：`claude/qc-model-fulltest`

---

## 1. 推理入口 / MNN 封装层（Android）

| 文件 | 关键函数 | 当前是否被测 |
|------|---------|------------|
| `apps/android-qc/.../MnnRuntimeLoader.kt` | `load()`, `isStubMode()`, `inferenceBackend` | 否（B2 @device 测试覆盖） |
| `apps/android-qc/.../MnnQwenInspector.kt` | `inspect()`, `buildInferenceParams()`, `stubMode` | 否（B2 @device 测试覆盖） |

**stub_mode 判定**：`MNN.so` native 库加载失败 → `stubMode=true`（模拟输出）；加载成功 → `stubMode=false`（真实 MNN 推理）。位置：`MnnRuntimeLoader.load()` 返回值。

---

## 2. 三级视频管线（Python）

| 级别 | 文件 | 关键函数/类 | 当前是否被测 |
|------|------|-----------|------------|
| L1 帧差分 | `src/video/frame_filter.py` | `has_changed(prev_gray, curr_gray)` | `tests/test_video_pipeline.py` ✓ |
| L2 本地 CV 预筛 | `src/video/detector.py` | `HybridDetector.score()`, `above_threshold()` | `tests/test_video_pipeline.py` ✓ |
| L3 比对器 | `src/cv/comparator.py`, `src/llm/` | `CVComparator.compare_images()` | `tests/test_cv_comparator.py` ✓ |
| 管线编排 | `src/video/pipeline.py` | `run_video_pipeline()` | `tests/test_video_pipeline.py` ✓ |

**关键配置**：
- `TIER1_DIFF_THRESHOLD`（默认 5）：`src/config.py::tier1_diff_threshold()`，`src/video/frame_filter.py`
- `LOCAL_PREFILTER_THRESHOLD`（默认 0.25）：`src/config.py::local_prefilter_threshold()`，`src/video/detector.py::above_threshold()`

---

## 3. QcResultParser（Python — 已知 Bug 点）

| 位置 | 函数 | 已知问题 | 是否被测 |
|------|------|---------|--------|
| `src/llm/qwen_provider.py::_extract_json()` | JSON 抽取 | **无 `<think>` 剥离** — 主要 Bug！ | 否（已修复，委托新 `QcResultParser`） |
| `src/llm/result_parser.py::QcResultParser` | 统一解析层（新建） | 修复上述 Bug；fail-closed 设计 | 新增 `tests/test_parser.py`（18 用例，≥90% 分支覆盖目标） |
| `apps/android-qc/.../QcResultParser.kt` | Kotlin 端 `stripThinkingBlocks()` | Kotlin 层已正确实现 | Android 单测（本 plan 范围外） |

**修复路径**：`src/llm/qwen_provider.py` 的 `_extract_json()` 函数改为调用 `QcResultParser.parse(raw_text)`，完全消除 `<think>` 回归风险。

---

## 4. abcdYi 契约

| 项目 | 位置 | 说明 |
|------|------|------|
| 结果事件结构 | `src/db/models.py::QCResult` | 字段：`overall_result`, `similarity_score`, `severity`, `feedback_zh/en`, `deviations`(JSON), `llm_provider`, `model_name`, `elapsed_ms` |
| SKU/租户身份注入链 | `SampleItem.sku_id` → `QCTask.sample_id` → `QCResult.task_id` | FK 三级链 |
| Append-only 语义 | `src/qc/comparison.py::run_comparison()` | 每次调用 INSERT 新 QCResult 行，无 UPDATE/DELETE |
| Event schema | `src/db/models.py` + `src/qc/comparison.py` | `run_comparison()` 写入 QCResult，无修改路径 |

---

## 5. 现有测试（基线，claude/new-session-qcgn1p 上）

| 文件 | 覆盖内容 | 类型 |
|------|---------|------|
| `tests/test_cv_comparator.py` | CVComparator 各阈值、图像比对逻辑 | 离线 |
| `tests/test_db_schema.py` | SQLAlchemy ORM 模型、关系映射 | 离线 |
| `tests/test_llm_layer.py` | MockProvider, OpenAIProvider, registry 路由 | 离线（mock） |
| `tests/test_qc_comparison.py` | run_comparison, task/result 持久化 | 离线（mock/cv） |
| `tests/test_sample_store.py` | import_sample, get_samples | 离线 |
| `tests/test_video_pipeline.py` | L1/L2/L3 管线、帧差分、HybridDetector | 离线 |

**缺失覆盖**（本 plan 新增）：
- `QcResultParser`（Python 层 `<think>` 剥离 + JSON 抽取 + fail-closed）→ `tests/test_parser.py`
- `DashScopeOpenAIProvider`（B1 云端真实调用）→ `tests/test_cloud_b1.py` `@real_api`
- abcdYi 契约显式验证（append-only、SKU 链、enum 校验）→ `tests/test_e2e_abcdyi.py`
- 性能 / 延迟预算 / 成本闸 → `tests/test_performance.py`

---

## 6. 云端可用模型（B1 probe 待确认）

默认模型：`qwen3-vl-8b-instruct`（OpenAI 兼容接口，非思考 instruct 规格）  
备用 oracle：`qwen3-vl-plus`（`QWEN_ORACLE_MODEL` 环境变量覆盖）  
实际可用名称由 `tests/test_cloud_b1.py::TestCloudProbe::test_probe_available_models` 在 B1 运行时确认，结果写入 `tests/snapshots/cloud/probe_models.json`。

---

## 7. 未覆盖分支清单（Step 2 测试完成后由 pytest-cov 输出更新）

- `QcResultParser.parse()` — 所有 error 分支（新建，由 `tests/test_parser.py` 18 用例覆盖）
- `QcResultParser.extract_json_str()` — markdown fence / 裸 JSON / 无 JSON 三路径
- `DashScopeOpenAIProvider` — 网络调用路径（@real_api 覆盖）
- `registry.get_provider("dashscope_openai")` — 新增路由（test_llm_layer.py 扩展覆盖）
- Android MNN `stubMode=false` 真实推理路径（B2 @device 覆盖）
- `run_video_pipeline` 单帧解码失败路径（现有 test_video_pipeline.py 部分覆盖）
