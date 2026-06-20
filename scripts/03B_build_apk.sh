#!/usr/bin/env bash
# 03B_build_apk.sh — GiraffeQC Pad 编译脚本（仅编译，不安装）
#
# 【工作流说明】
#   此脚本在有网环境下运行（Pad 未连接），只做编译。
#   安装到 Pad 用 03B_pad_install_android13.sh --skip-build
#
# 用法:
#   cd ~/giraffe-qc-model
#   bash scripts/03B_build_apk.sh
#
# 成功后产出:
#   apps/android-qc/app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANDROID_QC_DIR="$REPO_ROOT/apps/android-qc"
APK_PATH="$ANDROID_QC_DIR/app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk"
JNI_DIR="$ANDROID_QC_DIR/app/src/main/jniLibs/arm64-v8a"
SYNC_FILE="$REPO_ROOT/.last_synced_commit"

step() { echo ""; echo "============================================"; echo "[$1] $2"; echo "============================================"; }
ok()   { echo "✅  $*"; }
warn() { echo "⚠️   $*"; }
fail() { echo ""; echo "❌  失败: $*" >&2; exit 1; }

TOTAL=6
N=0
next() { N=$((N+1)); step "$N/$TOTAL" "$1"; }

# ─────────────────────────────────────────────────────────────────────────────
# [1/6] 确认本地代码完整
# ─────────────────────────────────────────────────────────────────────────────
next "确认本地代码完整"

[[ -d "$ANDROID_QC_DIR" ]] || fail "apps/android-qc 不存在，请先运行 03A_pull_code.sh"
[[ -x "$ANDROID_QC_DIR/gradlew" ]] || fail "gradlew 不存在，请先运行 03A_pull_code.sh"

LOCAL_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo '')"
if [[ -n "$LOCAL_COMMIT" ]]; then
    echo "  当前 commit: $LOCAL_COMMIT"
fi
if [[ -f "$SYNC_FILE" ]]; then
    SYNCED_COMMIT="$(cat "$SYNC_FILE")"
    if [[ "$LOCAL_COMMIT" == "$SYNCED_COMMIT" ]]; then
        ok "当前代码 commit 与上次 03A 同步记录一致: $LOCAL_COMMIT"
    else
        warn "当前 commit ($LOCAL_COMMIT) 与上次 03A 同步 ($SYNCED_COMMIT) 不一致"
        warn "建议先运行 03A_pull_code.sh 拉取最新代码"
    fi
else
    warn "未找到 03A 同步记录，建议先运行 03A_pull_code.sh"
fi
ok "本地代码完整: $ANDROID_QC_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# [2/6] 检查外网连接（Gradle 需要下载依赖）
# ─────────────────────────────────────────────────────────────────────────────
next "检查外网连接"

if curl -fsS --max-time 5 "https://dl.google.com/dl/android/maven2/index.xml" -o /dev/null 2>/dev/null; then
    ok "可以访问 Google Maven 仓库"
else
    warn "无法访问 Google Maven — 如果 Gradle 依赖已缓存可继续，否则编译会失败"
fi

# ─────────────────────────────────────────────────────────────────────────────
# [3/6] 检查 Android SDK
# ─────────────────────────────────────────────────────────────────────────────
next "检查 Android SDK 位置"

SDK_HOME=""
for candidate in \
    "${ANDROID_HOME:-}" \
    "${ANDROID_SDK_ROOT:-}" \
    "$HOME/Library/Android/sdk" \
    "$HOME/Android/Sdk"; do
    [[ -n "$candidate" && -d "$candidate/platform-tools" ]] && SDK_HOME="$candidate" && break
done

if [[ -z "$SDK_HOME" ]]; then
    fail "未找到 Android SDK。请通过 Android Studio 安装，或设置 ANDROID_HOME 环境变量"
fi
ok "使用 Android SDK: $SDK_HOME"

LOCAL_PROPS="$ANDROID_QC_DIR/local.properties"
echo "sdk.dir=$SDK_HOME" > "$LOCAL_PROPS"
ok "已生成: $LOCAL_PROPS"

# ─────────────────────────────────────────────────────────────────────────────
# [4/6] 检查 MNN 原生库文件
# ─────────────────────────────────────────────────────────────────────────────
next "检查 MNN 原生库文件"

MISSING_LIBS=()
for lib in libMNN.so libMNN_Express.so libllm.so; do
    f="$JNI_DIR/$lib"
    if [[ -f "$f" ]]; then
        SIZE=$(du -sh "$f" | cut -f1)
        echo "   ✅  $lib ($SIZE)"
    else
        MISSING_LIBS+=("$lib")
        echo "   ❌  $lib — 缺失"
    fi
done

if [[ ${#MISSING_LIBS[@]} -gt 0 ]]; then
    echo ""
    warn "缺少以下 MNN 原生库: ${MISSING_LIBS[*]}"
    warn "请运行: bash scripts/download_mnn_android_libs.sh"
    warn "（需要 Android NDK r25c+ 和约 15 分钟编译时间）"
    fail "MNN 原生库不完整，无法链接 APK"
fi
ok "所有必需的 MNN 原生库都已存在"

# ─────────────────────────────────────────────────────────────────────────────
# [5/6] 检查 llm.hpp 头文件
# ─────────────────────────────────────────────────────────────────────────────
next "检查 MNN 头文件"

LLM_HDR="$ANDROID_QC_DIR/mnn_android/include/llm/llm.hpp"
if [[ -f "$LLM_HDR" ]]; then
    ok "llm.hpp 存在"
else
    fail "llm.hpp 不存在: $LLM_HDR\n请运行: bash scripts/download_mnn_android_libs.sh"
fi

# ─────────────────────────────────────────────────────────────────────────────
# [6/6] 编译 APK
# ─────────────────────────────────────────────────────────────────────────────
next "编译 APK (padLocalDebug)"

echo "  ⚠️  请勿在编译期间连接 Pad（会断网）"
echo ""

(cd "$ANDROID_QC_DIR" && ./gradlew :app:assemblePadLocalDebug)

echo ""
if [[ -f "$APK_PATH" ]]; then
    APK_SIZE=$(du -sh "$APK_PATH" | cut -f1)
    ok "APK 编译成功 ($APK_SIZE)"
    echo ""
    echo "  输出路径: $APK_PATH"
    echo ""
    echo "  APK 内原生库:"
    unzip -l "$APK_PATH" 2>/dev/null | grep "lib/arm64-v8a/" | awk '{print "    "$NF}' || true
    echo ""
    echo "  下一步（连接 Pad 后）:"
    echo "    bash scripts/03B_pad_install_android13.sh --skip-build"
else
    # 搜索实际生成的 APK（用于诊断路径问题）
    echo "  搜索实际生成的 APK 位置..."
    FOUND=$(find "$ANDROID_QC_DIR/app/build/outputs/apk" -name "*.apk" 2>/dev/null | head -5)
    if [[ -n "$FOUND" ]]; then
        echo "$FOUND"
        echo ""
        warn "APK 已生成但路径与预期不同。预期路径:"
        warn "  $APK_PATH"
        warn "实际路径见上方。请更新脚本中的 APK_PATH 变量。"
    else
        fail "编译未生成 APK，请检查上方 Gradle 输出"
    fi
fi
