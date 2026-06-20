#!/usr/bin/env bash
# Deploy GiraffeQC APK to the Android Pad.
#
# IMPORTANT — two-phase workflow:
#   Phase 1 (NEEDS INTERNET)  : build APK with gradlew; run BEFORE connecting to Pad.
#   Phase 2 (NO INTERNET)     : install via ADB; run AFTER connecting to Pad.
#
# Usage:
#   # Build only (internet required):
#   ./scripts/deploy_to_pad.sh --build-only
#
#   # Install only (pad must be connected via USB):
#   ./scripts/deploy_to_pad.sh --install-only
#
#   # Build + install in one run (only works if Mac stays online while pad is connected):
#   ./scripts/deploy_to_pad.sh
#
# Options:
#   --build-only      Only build the APK; skip ADB install.
#   --install-only    Skip build; install the pre-built APK to the connected pad.
#   --device SERIAL   ADB device serial (default: first connected device).
#   --apk PATH        Path to a pre-built APK to install (only with --install-only).
#   --model-dir PATH  Local model directory to push to device (default: skip model push).
#   --help            Show this help.
#
# See docs/PAD_LOCAL_MNN_DEPLOYMENT.md for full deployment instructions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANDROID_QC_DIR="$REPO_ROOT/apps/android-qc"
DEFAULT_APK_PATH="$ANDROID_QC_DIR/app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk"

BUILD=true
INSTALL=true
DEVICE=""
APK_PATH=""
MODEL_DIR=""

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-only)   INSTALL=false; shift ;;
        --install-only) BUILD=false;   shift ;;
        --device)       DEVICE="$2";   shift 2 ;;
        --apk)          APK_PATH="$2"; shift 2 ;;
        --model-dir)    MODEL_DIR="$2"; shift 2 ;;
        --help|-h)      usage ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

log()  { echo "▶  $*"; }
ok()   { echo "✅ $*"; }
warn() { echo "⚠️  $*"; }
fail() { echo "❌ $*" >&2; exit 1; }

ADB_CMD="adb"
[[ -n "$DEVICE" ]] && ADB_CMD="adb -s $DEVICE"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — BUILD (requires internet on first run to download Gradle deps)
# ─────────────────────────────────────────────────────────────────────────────
if $BUILD; then
    echo ""
    echo "============================================"
    echo " PHASE 1: Build APK (internet required)"
    echo "============================================"
    echo " ⚠️  Do NOT connect the Pad yet if connecting"
    echo "     the Pad cuts off your internet access."
    echo "============================================"
    echo ""

    if [[ ! -x "$ANDROID_QC_DIR/gradlew" ]]; then
        fail "gradlew not found at $ANDROID_QC_DIR/gradlew. Run: git pull origin android-pad-app"
    fi

    log "Running ./gradlew :app:assemblePadLocalDebug ..."
    (cd "$ANDROID_QC_DIR" && ./gradlew :app:assemblePadLocalDebug)

    APK_PATH="$DEFAULT_APK_PATH"
    if [[ ! -f "$APK_PATH" ]]; then
        fail "APK not produced at expected path: $APK_PATH"
    fi
    ok "APK built: $APK_PATH"
fi

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — INSTALL (no internet needed; pad must be connected via USB)
# ─────────────────────────────────────────────────────────────────────────────
if $INSTALL; then
    echo ""
    echo "============================================"
    echo " PHASE 2: Install to Pad (ADB / USB only)"
    echo "============================================"
    echo ""

    # Resolve APK path
    if [[ -z "$APK_PATH" ]]; then
        APK_PATH="$DEFAULT_APK_PATH"
    fi
    if [[ ! -f "$APK_PATH" ]]; then
        fail "APK not found: $APK_PATH\nRun build phase first: $0 --build-only"
    fi

    # Wait for ADB device
    log "Waiting for ADB device (up to 60 s) ..."
    for i in $(seq 1 12); do
        if $ADB_CMD get-state &>/dev/null 2>&1; then
            break
        fi
        if [[ $i -eq 12 ]]; then
            fail "No ADB device found after 60 s.\nEnable USB debugging on the Pad and connect via USB."
        fi
        echo "   ...waiting for device ($((i*5))/60 s)"
        sleep 5
    done

    DEVICE_MODEL=$($ADB_CMD shell getprop ro.product.model 2>/dev/null | tr -d '\r')
    ANDROID_VER=$($ADB_CMD shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
    ok "Device connected: $DEVICE_MODEL (Android $ANDROID_VER)"

    log "Installing APK ..."
    $ADB_CMD install -r "$APK_PATH"
    ok "APK installed."

    # Optional: push model files
    if [[ -n "$MODEL_DIR" ]]; then
        DEVICE_MODEL_PATH="/sdcard/qwen3_vl_4b_mnn"
        log "Pushing model files: $MODEL_DIR → $DEVICE_MODEL_PATH"
        $ADB_CMD push "$MODEL_DIR" "$DEVICE_MODEL_PATH"
        ok "Model files pushed."

        log "Verifying model files on device ..."
        FILE_COUNT=$($ADB_CMD shell "ls $DEVICE_MODEL_PATH | wc -l" 2>/dev/null | tr -d '\r ')
        if [[ "$FILE_COUNT" -lt 10 ]]; then
            warn "Only $FILE_COUNT file(s) found at $DEVICE_MODEL_PATH — expected ≥10. Verify manually."
        else
            ok "Model files verified ($FILE_COUNT files present)."
        fi
    else
        warn "No --model-dir specified; skipping model push."
        warn "Push model manually: adb push <local_model_dir>/ /sdcard/qwen3_vl_4b_mnn/"
    fi

    echo ""
    ok "Deployment complete."
    echo ""
    echo "Next steps:"
    echo "  - Launch the GiraffeQC app on the Pad"
    echo "  - Run benchmark: ./scripts/benchmark_mnn.sh"
fi
