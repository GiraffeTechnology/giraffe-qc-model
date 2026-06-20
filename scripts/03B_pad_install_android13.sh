#!/usr/bin/env bash
# 03B_pad_install_android13.sh — GiraffeQC Pad 部署脚本（Android 13）
#
# 与 03 的唯一区别：编译 APK（需要联网）放在连接 Pad（断网）之前。
#
# 用法:
#   ./scripts/03B_pad_install_android13.sh [选项]
#
# 选项:
#   --skip-build        跳过编译，使用已有 APK（APK 已在上次编译中生成）
#   --skip-model        跳过模型文件推送
#   --model-dir PATH    本地模型目录路径（默认: ./Qwen3-VL-4B-Instruct-MNN）
#   --device SERIAL     指定 ADB 设备序列号（默认: 第一个已连接设备）
#   --help              显示帮助
#
# 正常用法（首次 / 每次更新代码后）:
#   cd ~/giraffe-qc-model
#   ./scripts/03B_pad_install_android13.sh
#
# 只重装 APK，不重推模型:
#   ./scripts/03B_pad_install_android13.sh --skip-model
#
# 只推模型，不重编译也不重装 APK:
#   ./scripts/03B_pad_install_android13.sh --skip-build --skip-model  # (no-op, 用 adb push 即可)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANDROID_QC_DIR="$REPO_ROOT/apps/android-qc"
APK_PATH="$ANDROID_QC_DIR/app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk"
DEFAULT_MODEL_DIR="$REPO_ROOT/Qwen3-VL-4B-Instruct-MNN"
DEVICE_MODEL_PATH="/sdcard/qwen3_vl_4b_mnn"
PACKAGE="com.giraffetechnology.qc"

SKIP_BUILD=false
SKIP_MODEL=false
MODEL_DIR="$DEFAULT_MODEL_DIR"
DEVICE=""

for arg in "$@"; do
    case "$arg" in
        --skip-build)  SKIP_BUILD=true ;;
        --skip-model)  SKIP_MODEL=true ;;
        --help|-h)     grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    esac
done
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model-dir) MODEL_DIR="$2"; shift 2 ;;
        --device)    DEVICE="$2";    shift 2 ;;
        *)           shift ;;
    esac
done

ADB_CMD="adb"
[[ -n "$DEVICE" ]] && ADB_CMD="adb -s $DEVICE"

step() { echo ""; echo "============================================"; echo "[$1] $2"; echo "============================================"; }
ok()   { echo "✅  $*"; }
warn() { echo "⚠️   $*"; }
fail() { echo ""; echo "❌  失败: $*" >&2; exit 1; }

TOTAL=7
$SKIP_BUILD  && TOTAL=5
$SKIP_MODEL  && TOTAL=$((TOTAL - 1))

N=0
next() { N=$((N+1)); step "$N/$TOTAL" "$1"; }

# ─────────────────────────────────────────────────────────────────────────────
# [1] 检查前提条件
# ─────────────────────────────────────────────────────────────────────────────
next "检查前提条件"

if ! $SKIP_BUILD; then
    [[ -x "$ANDROID_QC_DIR/gradlew" ]] \
        || fail "gradlew 不存在。请先执行: git pull origin android-pad-app"
fi
if ! command -v adb &>/dev/null; then
    fail "adb 未找到，请确认 Android SDK platform-tools 已加入 PATH"
fi
ok "前提条件检查通过"

# ─────────────────────────────────────────────────────────────────────────────
# [2/3] 编译 APK — 必须在连接 Pad 之前完成（连 Pad 后断外网）
# ─────────────────────────────────────────────────────────────────────────────
if ! $SKIP_BUILD; then
    next "编译 APK（需要联网，请勿此时连接 Pad）"
    echo "  ⚠️  连接 Pad 会断开外网。编译必须在此之前完成。"
    echo ""
    (cd "$ANDROID_QC_DIR" && ./gradlew :app:assemblePadLocalDebug)
    [[ -f "$APK_PATH" ]] || fail "APK 未生成: $APK_PATH"
    ok "APK 编译成功: $APK_PATH"

    next "验证 AndroidManifest — 确认无 INTERNET 权限"
    (cd "$ANDROID_QC_DIR" && ./gradlew :app:processPadLocalDebugManifest --quiet)
    if grep -rq "android.permission.INTERNET" \
        "$ANDROID_QC_DIR/app/build/intermediates/merged_manifests/" 2>/dev/null; then
        fail "检测到 INTERNET 权限！Pad 应用不允许联网，请检查 AndroidManifest.xml"
    fi
    ok "PASS: 无 INTERNET 权限"
fi

# ─────────────────────────────────────────────────────────────────────────────
# [N] 等待 Pad 连接
# ─────────────────────────────────────────────────────────────────────────────
next "连接 Pad（现在可以插 USB / 连 Wi-Fi）"
echo "  请将 Pad 通过 USB 连接到本机，并确认已开启 USB 调试。"
echo "  等待 ADB 设备（最长 120 秒）..."
for i in $(seq 1 24); do
    if $ADB_CMD get-state &>/dev/null 2>&1; then break; fi
    if [[ $i -eq 24 ]]; then
        fail "120 秒内未检测到 ADB 设备。\n请检查 USB 连接并在设备上允许 USB 调试。"
    fi
    printf "   ...%ds\r" $((i*5))
    sleep 5
done
DEVICE_MODEL=$($ADB_CMD shell getprop ro.product.model 2>/dev/null | tr -d '\r')
ANDROID_VER=$($ADB_CMD shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
ok "设备已连接: $DEVICE_MODEL (Android $ANDROID_VER)"

# ─────────────────────────────────────────────────────────────────────────────
# [N] 安装 APK
# ─────────────────────────────────────────────────────────────────────────────
next "安装 APK"
[[ -f "$APK_PATH" ]] || fail "APK 不存在: $APK_PATH\n请先运行编译: $0（不加 --skip-build）"
$ADB_CMD install -r "$APK_PATH"
ok "APK 安装完成"

# ─────────────────────────────────────────────────────────────────────────────
# [N] 推送模型文件（可选）
# ─────────────────────────────────────────────────────────────────────────────
if ! $SKIP_MODEL; then
    next "推送模型文件"
    if [[ ! -d "$MODEL_DIR" ]]; then
        warn "模型目录不存在: $MODEL_DIR"
        warn "跳过模型推送。手动推送: adb push <模型目录>/ $DEVICE_MODEL_PATH/"
    else
        echo "  推送 $MODEL_DIR → 设备 $DEVICE_MODEL_PATH ..."
        $ADB_CMD push "$MODEL_DIR/" "$DEVICE_MODEL_PATH"
        FILE_COUNT=$($ADB_CMD shell "ls $DEVICE_MODEL_PATH | wc -l" 2>/dev/null | tr -d '\r ')
        if [[ "$FILE_COUNT" -lt 10 ]]; then
            warn "设备上只有 $FILE_COUNT 个文件，预期 ≥10，请手动核验"
        else
            ok "模型文件推送完成（$FILE_COUNT 个文件）"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# [N] 完成
# ─────────────────────────────────────────────────────────────────────────────
next "部署完成"
ok "GiraffeQC 已安装到 $DEVICE_MODEL"
echo ""
echo "  下一步:"
echo "    - 在 Pad 上启动 GiraffeQC 应用"
echo "    - 运行基准测试: ./scripts/benchmark_mnn.sh"
echo ""
