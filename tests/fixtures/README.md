# tests/fixtures — 测试夹具说明

## 目录结构

```
tests/fixtures/
├── good/                   # 合格件：期望 overall_result=pass
├── defect_scratch/         # 划痕缺陷：期望 reject 或 needs_fix
├── defect_dent/            # 凹陷缺陷：期望 reject 或 needs_fix
├── defect_missing_part/    # 缺件：期望 reject
├── ambiguous/              # 边界件：pass/needs_fix 均可接受
├── hard/                   # 暗光/旋转/反光：不强求方向，不得崩溃
├── red_square.png          # 基础测试图（现有）
├── red_square_with_dot.png # 带点缺陷（现有）
└── blue_square.png         # 蓝色方块（现有）
```

## PNG 图片文件

每个子目录里的 `.png` 文件为合成图片，由脚本生成：

```bash
python scripts/generate_test_fixtures.py
```

也可以替换为真实产品照片以提高大模型测试质量。

## 黄金样本（*.expected.json）

每个 `.expected.json` 定义人工确定的期望输出，用于解析层和端云一致性比对。

| 字段 | 说明 |
|------|------|
| `category` | 夹具类别 |
| `expected_overall_result` | 期望判定（null 表示不强求） |
| `expected_severity` | 期望严重程度（null 表示不强求） |
| `confidence_window` | 容许区间（ambiguous 类） |
| `must_not_crash` | 必须不崩溃（hard 类） |

## 保密说明

- 合成图片可入库
- 真实产品照片若含隐私，放入 `.gitignore` 并在此注明本地路径
- `tests/snapshots/**/raw_*` 已加入 `.gitignore`（可能含原始图像数据）
