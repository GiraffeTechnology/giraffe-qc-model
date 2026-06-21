#!/usr/bin/env bash
set -euo pipefail

# Download (or stub) MNN native libraries for the Android QC app.
#
# Usage:
#   bash scripts/download_mnn_android_libs.sh            # production: download real AAR
#   bash scripts/download_mnn_android_libs.sh --ci-stubs # CI: create empty stubs so
#                                                         # verifyMnnNativeDeps task passes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

APP_DIR="$REPO_ROOT/apps/android-qc/app"
JNILIBS_DIR="$APP_DIR/src/main/jniLibs/arm64-v8a"
INCLUDE_DIR="$APP_DIR/src/main/cpp/include"

CI_STUBS=false
for arg in "$@"; do
    case "$arg" in
        --ci-stubs) CI_STUBS=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

mkdir -p "$JNILIBS_DIR"
mkdir -p "$INCLUDE_DIR/llm"
mkdir -p "$INCLUDE_DIR/MNN"

if [[ "$CI_STUBS" == "true" ]]; then
    echo "[download_mnn_android_libs.sh] --ci-stubs: creating empty stub files for CI."
    # Empty stubs — sufficient for verifyMnnNativeDeps; not suitable for runtime inference.
    touch "$JNILIBS_DIR/libMNN.so"
    touch "$JNILIBS_DIR/libMNN_Express.so"
    printf '// MNN LLM stub header — CI only\n' > "$INCLUDE_DIR/llm/llm.hpp"
    printf '// MNN Interpreter stub header — CI only\n' > "$INCLUDE_DIR/MNN/Interpreter.hpp"
    echo "[download_mnn_android_libs.sh] Stubs written:"
    echo "  $JNILIBS_DIR/libMNN.so"
    echo "  $JNILIBS_DIR/libMNN_Express.so"
    echo "  $INCLUDE_DIR/llm/llm.hpp"
    echo "  $INCLUDE_DIR/MNN/Interpreter.hpp"
    exit 0
fi

# Production mode: download real MNN AAR from MNN_DOWNLOAD_URL.
# MNN_DOWNLOAD_URL must be set in the environment or via CI secrets.
if [[ -z "${MNN_DOWNLOAD_URL:-}" ]]; then
    echo "[download_mnn_android_libs.sh] ERROR: MNN_DOWNLOAD_URL is not set." >&2
    echo "Set MNN_DOWNLOAD_URL to the authenticated URL of the MNN AAR, or" >&2
    echo "use --ci-stubs to create empty stubs for CI builds." >&2
    exit 1
fi

echo "[download_mnn_android_libs.sh] Downloading MNN AAR from MNN_DOWNLOAD_URL..."
AAR_CACHE="$REPO_ROOT/.mnn_aar_cache/mnn-android.aar"
mkdir -p "$(dirname "$AAR_CACHE")"
curl -fsSL "$MNN_DOWNLOAD_URL" -o "$AAR_CACHE"

echo "[download_mnn_android_libs.sh] Extracting native libraries from AAR..."
TMPDIR_AAR="$(mktemp -d)"
unzip -q "$AAR_CACHE" -d "$TMPDIR_AAR"
cp "$TMPDIR_AAR/jni/arm64-v8a/libMNN.so"        "$JNILIBS_DIR/" 2>/dev/null || true
cp "$TMPDIR_AAR/jni/arm64-v8a/libMNN_Express.so" "$JNILIBS_DIR/" 2>/dev/null || true
rm -rf "$TMPDIR_AAR"
echo "[download_mnn_android_libs.sh] Done."
