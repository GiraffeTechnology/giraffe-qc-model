#!/usr/bin/env bash
# Download MNN Android pre-built libraries and LLM headers for arm64-v8a.
#
# After running this script:
#   apps/android-qc/mnn_android/include/llm/llm.hpp  <- MNN LLM API header
#   apps/android-qc/mnn_android/include/MNN/         <- Core MNN headers
#   apps/android-qc/app/src/main/jniLibs/arm64-v8a/libMNN.so
#   apps/android-qc/app/src/main/jniLibs/arm64-v8a/libMNN_Express.so
#
# These files are git-ignored (large binaries). Re-run after a clean checkout.
#
# Usage:
#   bash scripts/download_mnn_android_libs.sh
#   MNN_VERSION=3.0.0 bash scripts/download_mnn_android_libs.sh
#
# If automatic download fails, see manual instructions printed below.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MNN_ANDROID_DIR="$REPO_ROOT/apps/android-qc/mnn_android"
JNI_LIB_DIR="$REPO_ROOT/apps/android-qc/app/src/main/jniLibs/arm64-v8a"
MNN_VERSION="${MNN_VERSION:-3.0.0}"

echo "=== MNN Android Library Setup ==="
echo "MNN version : $MNN_VERSION"
echo "Headers dir : $MNN_ANDROID_DIR/include"
echo "Libs dir    : $JNI_LIB_DIR"
echo ""

mkdir -p "$MNN_ANDROID_DIR/include/llm"
mkdir -p "$MNN_ANDROID_DIR/include/MNN"
mkdir -p "$JNI_LIB_DIR"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# 1. Download MNN source for headers
# ---------------------------------------------------------------------------
MNN_SRC_URL="https://github.com/alibaba/MNN/archive/refs/tags/${MNN_VERSION}.zip"
echo "Downloading MNN $MNN_VERSION source (headers)..."
if curl -fsSL "$MNN_SRC_URL" -o "$WORK/mnn_src.zip" 2>/dev/null; then
    unzip -q "$WORK/mnn_src.zip" -d "$WORK/mnn_src"
    MNN_SRC="$(find "$WORK/mnn_src" -maxdepth 1 -type d -name 'MNN*' | head -1)"

    # Core headers
    if [ -d "$MNN_SRC/include" ]; then
        cp -r "$MNN_SRC/include/." "$MNN_ANDROID_DIR/include/"
        echo "[OK] Core headers copied"
    fi

    # LLM header -- search multiple known paths across MNN versions
    LLM_HDR=""
    for candidate in \
        "$MNN_SRC/transformers/llm/export/llm.hpp" \
        "$MNN_SRC/llm/include/llm.hpp" \
        "$MNN_SRC/include/llm/llm.hpp" \
        "$MNN_SRC/project/android/apps/MNNLLMChat/app/src/main/cpp/llm.hpp"; do
        if [ -f "$candidate" ]; then
            LLM_HDR="$candidate"
            break
        fi
    done
    if [ -n "$LLM_HDR" ]; then
        cp "$LLM_HDR" "$MNN_ANDROID_DIR/include/llm/llm.hpp"
        echo "[OK] llm.hpp -> $MNN_ANDROID_DIR/include/llm/llm.hpp"
    else
        echo "[WARN] llm.hpp not found in MNN $MNN_VERSION source."
        echo "       Search: find $WORK/mnn_src -name 'llm.hpp'"
        echo "       Then:   cp <found> $MNN_ANDROID_DIR/include/llm/llm.hpp"
    fi
else
    echo "[WARN] Could not download MNN $MNN_VERSION source."
fi

# ---------------------------------------------------------------------------
# 2. Download pre-built Android .so files
# Try AAR from release; fall back to build instructions.
# ---------------------------------------------------------------------------
AAR_URL="https://github.com/alibaba/MNN/releases/download/${MNN_VERSION}/MNN-${MNN_VERSION}-android.aar"
echo ""
echo "Trying pre-built AAR: $AAR_URL"
if curl -fsSL --head "$AAR_URL" -o /dev/null 2>/dev/null; then
    curl -fsSL "$AAR_URL" -o "$WORK/MNN-android.aar"
    unzip -q "$WORK/MNN-android.aar" 'jni/arm64-v8a/*.so' -d "$WORK/aar" 2>/dev/null || true
    for so in libMNN.so libMNN_Express.so libMNN_CL.so; do
        src="$WORK/aar/jni/arm64-v8a/$so"
        if [ -f "$src" ]; then
            cp "$src" "$JNI_LIB_DIR/$so"
            echo "[OK] $so"
        fi
    done
else
    echo "Pre-built AAR not found at release URL."
fi

# ---------------------------------------------------------------------------
# 3. Verify + manual instructions if still missing
# ---------------------------------------------------------------------------
echo ""
echo "=== Required file status ==="
ALL_OK=true
for f in \
    "$MNN_ANDROID_DIR/include/llm/llm.hpp" \
    "$JNI_LIB_DIR/libMNN.so" \
    "$JNI_LIB_DIR/libMNN_Express.so"; do
    if [ -f "$f" ]; then
        echo "  [OK]      $f"
    else
        echo "  [MISSING] $f"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo "=== Manual build instructions ==="
    echo "If the download failed, build MNN for Android arm64-v8a:"
    echo ""
    echo "  git clone https://github.com/alibaba/MNN.git --branch $MNN_VERSION --depth 1"
    echo "  cd MNN && mkdir build_android && cd build_android"
    echo "  cmake .. \\"
    echo "    -DCMAKE_TOOLCHAIN_FILE=\$NDK/build/cmake/android.toolchain.cmake \\"
    echo "    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 \\"
    echo "    -DMNN_BUILD_FOR_ANDROID=ON -DMNN_BUILD_LLM=ON \\"
    echo "    -DCMAKE_BUILD_TYPE=Release"
    echo "  cmake --build . --parallel"
    echo "  cp libMNN.so libMNN_Express.so $JNI_LIB_DIR/"
    echo "  cp ../transformers/llm/export/llm.hpp $MNN_ANDROID_DIR/include/llm/"
    echo "  cp -r ../include/. $MNN_ANDROID_DIR/include/"
    echo ""
    echo "See docs/PAD_LOCAL_MNN_DEPLOYMENT.md for full deployment instructions."
    exit 1
fi

echo ""
echo "All required MNN Android files are present. Build with:"
echo "  cd apps/android-qc && ./gradlew :app:assemblePadLocalDebug"
