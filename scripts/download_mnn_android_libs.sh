#!/usr/bin/env bash
# Build MNN Android native libraries (arm64-v8a) from source and install headers.
#
# MNN does NOT publish pre-built Android AARs on GitHub releases.
# This script downloads the MNN source and compiles it with the Android NDK.
#
# After running this script the following files will be present:
#   apps/android-qc/mnn_android/include/llm/llm.hpp
#   apps/android-qc/mnn_android/include/MNN/Interpreter.hpp  (+ other MNN headers)
#   apps/android-qc/app/src/main/jniLibs/arm64-v8a/libMNN.so
#   apps/android-qc/app/src/main/jniLibs/arm64-v8a/libMNN_Express.so
#
# These files are git-ignored (large binaries). Re-run after a clean checkout.
#
# Requirements:
#   - Android NDK r25c+ (auto-detected; see NDK search order below)
#   - CMake 3.22+ (typically bundled with NDK, or use system cmake)
#   - Internet access to github.com (to download MNN source)
#   - ~4 GB disk space + ~15 min build time
#
# Usage:
#   bash scripts/download_mnn_android_libs.sh
#   MNN_VERSION=3.0.0 bash scripts/download_mnn_android_libs.sh
#
# NDK search order (first found wins):
#   1. $NDK_HOME
#   2. $ANDROID_NDK_HOME
#   3. $ANDROID_HOME/ndk/<latest>
#   4. ~/Library/Android/sdk/ndk/<latest>   (macOS / Android Studio default)
#   5. ~/Android/Sdk/ndk/<latest>           (Linux / Android Studio default)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MNN_ANDROID_DIR="$REPO_ROOT/apps/android-qc/mnn_android"
JNI_LIB_DIR="$REPO_ROOT/apps/android-qc/app/src/main/jniLibs/arm64-v8a"
MNN_VERSION="${MNN_VERSION:-3.0.0}"

log()  { echo "▶  $*"; }
ok()   { echo "✅  $*"; }
warn() { echo "⚠️   $*"; }
fail() { echo ""; echo "❌  $*" >&2; exit 1; }

echo ""
echo "========================================"
echo " MNN Android Library Builder"
echo " MNN version : $MNN_VERSION"
echo " JNI libs    : $JNI_LIB_DIR"
echo " Headers     : $MNN_ANDROID_DIR/include"
echo "========================================"
echo ""

mkdir -p "$MNN_ANDROID_DIR/include/llm"
mkdir -p "$MNN_ANDROID_DIR/include/MNN"
mkdir -p "$JNI_LIB_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Find NDK
# ─────────────────────────────────────────────────────────────────────────────
find_ndk() {
    local toolchain="build/cmake/android.toolchain.cmake"

    # Explicit env vars
    for candidate in "${NDK_HOME:-}" "${ANDROID_NDK_HOME:-}" "${ANDROID_NDK:-}"; do
        [[ -n "$candidate" && -f "$candidate/$toolchain" ]] && echo "$candidate" && return
    done

    # $ANDROID_HOME/ndk/<version>
    if [[ -n "${ANDROID_HOME:-}" && -d "$ANDROID_HOME/ndk" ]]; then
        local v
        v=$(ls "$ANDROID_HOME/ndk" 2>/dev/null | sort -V | tail -1)
        [[ -n "$v" && -f "$ANDROID_HOME/ndk/$v/$toolchain" ]] \
            && echo "$ANDROID_HOME/ndk/$v" && return
    fi

    # macOS Android Studio default
    if [[ -d "$HOME/Library/Android/sdk/ndk" ]]; then
        local v
        v=$(ls "$HOME/Library/Android/sdk/ndk" | sort -V | tail -1)
        [[ -n "$v" && -f "$HOME/Library/Android/sdk/ndk/$v/$toolchain" ]] \
            && echo "$HOME/Library/Android/sdk/ndk/$v" && return
    fi

    # Linux Android Studio default
    if [[ -d "$HOME/Android/Sdk/ndk" ]]; then
        local v
        v=$(ls "$HOME/Android/Sdk/ndk" | sort -V | tail -1)
        [[ -n "$v" && -f "$HOME/Android/Sdk/ndk/$v/$toolchain" ]] \
            && echo "$HOME/Android/Sdk/ndk/$v" && return
    fi

    echo ""
}

NDK_DIR="$(find_ndk)"
if [[ -z "$NDK_DIR" ]]; then
    echo ""
    echo "NDK not found. Install Android NDK r25c+ via Android Studio:"
    echo "  Android Studio → SDK Manager → SDK Tools → NDK (Side by side)"
    echo ""
    echo "Or set NDK_HOME before running this script:"
    echo "  export NDK_HOME=~/Library/Android/sdk/ndk/25.2.9519653"
    echo "  bash scripts/download_mnn_android_libs.sh"
    fail "Android NDK not found — cannot build MNN .so files."
fi
ok "NDK found: $NDK_DIR"

# Find cmake (prefer NDK-bundled cmake, then system cmake)
CMAKE_BIN=""
for candidate in \
    "$NDK_DIR/../cmake/"*/bin/cmake \
    "${ANDROID_HOME:-}/cmake/"*/bin/cmake \
    "$HOME/Library/Android/sdk/cmake/"*/bin/cmake \
    "$(command -v cmake 2>/dev/null)"; do
    # Expand glob before checking
    for c in $candidate; do
        [[ -x "$c" ]] && CMAKE_BIN="$c" && break 2
    done
done
[[ -z "$CMAKE_BIN" ]] && fail "cmake not found. Install via Android Studio SDK Manager (CMake) or 'brew install cmake'."
ok "CMake: $CMAKE_BIN ($( "$CMAKE_BIN" --version | head -1 ))"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Download MNN source
# ─────────────────────────────────────────────────────────────────────────────
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

MNN_SRC_URL="https://github.com/alibaba/MNN/archive/refs/tags/${MNN_VERSION}.tar.gz"
log "Downloading MNN ${MNN_VERSION} source from GitHub..."
if ! curl -fL --progress-bar "$MNN_SRC_URL" -o "$WORK/mnn_src.tar.gz"; then
    fail "Download failed: $MNN_SRC_URL\nCheck internet access and that the tag '${MNN_VERSION}' exists."
fi

log "Extracting source..."
tar -xzf "$WORK/mnn_src.tar.gz" -C "$WORK"
MNN_SRC="$(find "$WORK" -maxdepth 1 -type d -name 'MNN-*' | head -1)"
[[ -z "$MNN_SRC" ]] && fail "Could not find extracted MNN source directory in $WORK"
ok "Source ready: $MNN_SRC"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Build MNN for arm64-v8a
# ─────────────────────────────────────────────────────────────────────────────
BUILD_DIR="$WORK/build_android"
mkdir -p "$BUILD_DIR"

log "Configuring CMake (arm64-v8a, Release, LLM enabled)..."
"$CMAKE_BIN" "$MNN_SRC" \
    -B "$BUILD_DIR" \
    -DCMAKE_TOOLCHAIN_FILE="$NDK_DIR/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a \
    -DANDROID_PLATFORM=android-26 \
    -DCMAKE_BUILD_TYPE=Release \
    -DMNN_BUILD_FOR_ANDROID=ON \
    -DMNN_BUILD_LLM=ON \
    -DMNN_SUPPORT_TRANSFORMER_FUSE=ON \
    -DMNN_BUILD_SHARED_LIBS=ON \
    -DMNN_BUILD_DEMO=OFF \
    -DMNN_BUILD_TEST=OFF \
    -DMNN_BUILD_BENCHMARK=OFF \
    -DMNN_BUILD_QUANTOOLS=OFF \
    -DMNN_BUILD_CONVERTER=OFF \
    2>&1 | grep -E "^--|CMake Warning|CMake Error|error:" || true

log "Building (this takes ~10–20 minutes on first run)..."
"$CMAKE_BIN" --build "$BUILD_DIR" \
    --target MNN MNN_Express \
    --parallel "$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 4)" \
    2>&1 | tail -5

# ─────────────────────────────────────────────────────────────────────────────
# 4. Copy .so files to jniLibs
# ─────────────────────────────────────────────────────────────────────────────
log "Copying .so files to $JNI_LIB_DIR ..."
COPIED_SO=0
for so in libMNN.so libMNN_Express.so; do
    src="$(find "$BUILD_DIR" -name "$so" | head -1)"
    if [[ -f "$src" ]]; then
        cp "$src" "$JNI_LIB_DIR/$so"
        SIZE=$(du -sh "$JNI_LIB_DIR/$so" | cut -f1)
        ok "$so  ($SIZE)"
        COPIED_SO=$((COPIED_SO + 1))
    else
        warn "$so not found in build output — check build logs."
    fi
done
# Optional: OpenCL backend
src="$(find "$BUILD_DIR" -name "libMNN_CL.so" | head -1)"
if [[ -f "$src" ]]; then
    cp "$src" "$JNI_LIB_DIR/libMNN_CL.so"
    ok "libMNN_CL.so  (OpenCL backend, optional)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. Copy headers
# ─────────────────────────────────────────────────────────────────────────────
log "Copying MNN headers..."

# Core headers
if [[ -d "$MNN_SRC/include" ]]; then
    cp -r "$MNN_SRC/include/." "$MNN_ANDROID_DIR/include/"
    ok "Core headers → $MNN_ANDROID_DIR/include/"
fi

# llm.hpp — search across known paths for different MNN versions
LLM_HDR=""
for candidate in \
    "$MNN_SRC/transformers/llm/export/llm.hpp" \
    "$MNN_SRC/llm/include/llm.hpp" \
    "$MNN_SRC/include/llm/llm.hpp" \
    "$MNN_SRC/project/android/apps/MNNLLMChat/app/src/main/cpp/llm.hpp" \
    "$BUILD_DIR/transformers/llm/export/llm.hpp"; do
    if [[ -f "$candidate" ]]; then
        LLM_HDR="$candidate"
        break
    fi
done

if [[ -n "$LLM_HDR" ]]; then
    cp "$LLM_HDR" "$MNN_ANDROID_DIR/include/llm/llm.hpp"
    ok "llm.hpp → $MNN_ANDROID_DIR/include/llm/llm.hpp"
else
    warn "llm.hpp not found in MNN $MNN_VERSION source tree."
    warn "Search manually: find $MNN_SRC -name 'llm.hpp'"
    warn "Then: cp <found> $MNN_ANDROID_DIR/include/llm/llm.hpp"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. Final status check
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo " Required file status"
echo "========================================"
ALL_OK=true
for f in \
    "$MNN_ANDROID_DIR/include/llm/llm.hpp" \
    "$JNI_LIB_DIR/libMNN.so" \
    "$JNI_LIB_DIR/libMNN_Express.so"; do
    if [[ -f "$f" ]]; then
        SIZE=$(du -sh "$f" | cut -f1)
        printf "  ✅  %-60s (%s)\n" "${f##$REPO_ROOT/}" "$SIZE"
    else
        printf "  ❌  %s\n" "${f##$REPO_ROOT/}"
        ALL_OK=false
    fi
done
echo ""

if [[ "$ALL_OK" = false ]]; then
    echo "Some required files are missing. Check the build log above."
    echo "Common causes:"
    echo "  - NDK version too old (need r25c+)"
    echo "  - MNN version doesn't support MNN_BUILD_LLM (need 3.x)"
    echo "  - cmake not found or wrong version"
    exit 1
fi

echo "All required files present. Next step:"
echo ""
echo "  cd apps/android-qc"
echo "  ./gradlew :app:assemblePadLocalDebug"
echo ""
