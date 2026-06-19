#!/usr/bin/env bash
# §4.3.0 On-device MNN benchmark runner.
# Target device: Snapdragon 8 Gen, 8 GB RAM, 128 GB storage.
# Default model: Qwen2-VL-2B-Instruct-MNN (INT4) — viable on 8 GB RAM.
#
# Usage:
#   ./scripts/benchmark_mnn.sh [OPTIONS]
#
# Options:
#   -d DEVICE      ADB device serial (default: first connected)
#   -i ITERATIONS  Number of inference iterations (default: 10)
#   -m MODEL_NAME  Model name label (default: Qwen2-VL-2B-Instruct-MNN)
#   -o OUTPUT      Local output file for JSON results (default: benchmark_results.json)
#   -a APK_PATH    Local path to app-debug.apk; installs before benchmark if provided
#   -c             CPU-only mode (disables GPU/NPU delegates, passes --ez cpu_only true)
#   -h             Show this help
#
# Prerequisites:
#   - ADB in PATH and device connected with USB debugging enabled
#   - APK installed (or pass -a <apk_path> to install automatically)
#   - Model pushed to device — choose ONE of:
#       (A) Public Downloads (preferred, ADB always has write access):
#           adb push <local_model_dir>/ /sdcard/Download/qwen_mnn/
#       (B) App-scoped staging (guaranteed fallback, no permissions needed):
#           adb push <local_model_dir>/ \
#             /sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen_mnn/
#     The app auto-imports to internal filesDir on first run (~2-3 min for 4 GB).
#     Subsequent runs skip the import.
#     See docs/DEPLOYMENT_LOCAL_QWEN.md for full instructions.
#
# Android 16 FUSE bypass: model is stored in internal filesDir (ext4) after import.
#   No MANAGE_EXTERNAL_STORAGE needed. Java File.exists() works on filesDir even
#   where /sdcard/ symlinks fail under Android 16 scoped storage.
#
# Model directory must contain (taobao-mnn/Qwen2-VL-2B-Instruct-MNN layout):
#   llm.mnn  llm.mnn.weight  visual.mnn  visual.mnn.weight
#   llm.mnn.json  llm_config.json  embeddings_bf16.bin  tokenizer.txt  config.json
#   checksum.sha256
#
# Budget targets (§4.3.0):
#   - Cold start load:  ≤ 30 s
#   - p95 per-image:    ≤ 10 s
#   - Peak memory:      ≤ 6 GB (leaves 2 GB headroom on 8 GB device)

set -euo pipefail

PACKAGE="com.giraffetechnology.qc"
ACTIVITY=".benchmark.BenchmarkActivity"
EXT_FILES_DIR="/sdcard/Android/data/${PACKAGE}/files"

DEVICE=""
ITERATIONS=10
MODEL_NAME="Qwen2-VL-2B-Instruct-MNN"
OUTPUT="benchmark_results.json"
APK_PATH=""
CPU_ONLY=false
DEVICE_OUTPUT="${EXT_FILES_DIR}/qc_benchmark_results.json"

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while getopts "d:i:m:o:a:ch" opt; do
    case $opt in
        d) DEVICE="$OPTARG" ;;
        i) ITERATIONS="$OPTARG" ;;
        m) MODEL_NAME="$OPTARG" ;;
        o) OUTPUT="$OPTARG" ;;
        a) APK_PATH="$OPTARG" ;;
        c) CPU_ONLY=true ;;
        h) usage ;;
        *) echo "Unknown option -$opt" >&2; exit 1 ;;
    esac
done

ADB_CMD="adb"
if [[ -n "$DEVICE" ]]; then
    ADB_CMD="adb -s $DEVICE"
fi

log() { echo "[benchmark_mnn] $*"; }

# Verify ADB connectivity
log "Checking ADB device..."
if ! $ADB_CMD get-state &>/dev/null; then
    echo "ERROR: No ADB device found. Connect device and enable USB debugging." >&2
    exit 1
fi

DEVICE_MODEL=$($ADB_CMD shell getprop ro.product.model 2>/dev/null | tr -d '\r')
ANDROID_VER=$($ADB_CMD shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
log "Device: $DEVICE_MODEL  (Android $ANDROID_VER)"

# Install APK if -a was provided
if [[ -n "$APK_PATH" ]]; then
    if [[ ! -f "$APK_PATH" ]]; then
        echo "ERROR: APK not found at: $APK_PATH" >&2
        exit 1
    fi
    log "Installing APK: $APK_PATH"
    $ADB_CMD install -r "$APK_PATH"
    log "APK installed."
fi

# Verify APK installed
if ! $ADB_CMD shell pm list packages 2>/dev/null | grep -q "$PACKAGE"; then
    echo "ERROR: APK not installed. Run:" >&2
    echo "  adb install app/build/outputs/apk/debug/app-debug.apk" >&2
    echo "  Or pass -a <apk_path> to this script." >&2
    exit 1
fi

# Check that at least one model source exists on device before launching.
# (filesDir is not accessible via adb without root, so we check staging sources.)
DOWNLOAD_SRC="/sdcard/Download/qwen_mnn"
STAGING_SRC="${EXT_FILES_DIR}/import/qwen_mnn"

MODEL_SRC_FOUND=false
if $ADB_CMD shell test -f "${DOWNLOAD_SRC}/llm.mnn" 2>/dev/null; then
    log "Model source: $DOWNLOAD_SRC (public Downloads)"
    MODEL_SRC_FOUND=true
elif $ADB_CMD shell test -f "${STAGING_SRC}/llm.mnn" 2>/dev/null; then
    log "Model source: $STAGING_SRC (app-scoped staging)"
    MODEL_SRC_FOUND=true
elif $ADB_CMD shell test -f "${EXT_FILES_DIR}/models/qwen_mnn/llm.mnn" 2>/dev/null; then
    log "Model already in app external files dir (legacy path — will be imported to filesDir)"
    MODEL_SRC_FOUND=true
fi

if [[ "$MODEL_SRC_FOUND" == "false" ]]; then
    echo "ERROR: llm.mnn not found in any source location." >&2
    echo "Push model to the device first (choose one):" >&2
    echo "  (A) adb push <local_dir>/ /sdcard/Download/qwen_mnn/" >&2
    echo "  (B) adb push <local_dir>/ ${STAGING_SRC}/" >&2
    echo "See docs/DEPLOYMENT_LOCAL_QWEN.md for download instructions." >&2
    exit 1
fi

log "Starting BenchmarkActivity..."
log "  iterations=$ITERATIONS  model_name=$MODEL_NAME  cpu_only=$CPU_ONLY"

# Clear logcat buffer so the fallback parser sees only this run's output
$ADB_CMD logcat -c 2>/dev/null || true

$ADB_CMD shell am start -n "${PACKAGE}/${ACTIVITY}" \
    --ei iterations "$ITERATIONS" \
    --es model_name "$MODEL_NAME" \
    --ez cpu_only "$CPU_ONLY"

# Wait for benchmark to finish. First run auto-imports ~4 GB (2-3 min); allow 15 min total.
log "Waiting for benchmark to complete (up to 15 min — first run imports model to internal storage)..."
TIMEOUT=900
ELAPSED=0
COMPLETED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
    if $ADB_CMD logcat -d -s QCBenchmark 2>/dev/null | grep -q "Benchmark complete"; then
        COMPLETED=1
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    log "  ...${ELAPSED}s elapsed"
done

if [[ $COMPLETED -eq 0 ]]; then
    echo "ERROR: Benchmark did not complete within ${TIMEOUT}s." >&2
    echo "Check logcat: adb logcat -s QCBenchmark" >&2
    exit 1
fi

log "Benchmark complete. Pulling results..."

# Pull JSON results
$ADB_CMD pull "$DEVICE_OUTPUT" "$OUTPUT" 2>/dev/null || {
    echo "WARNING: Could not pull $DEVICE_OUTPUT — extracting from logcat instead." >&2
    # Use -v raw to get only the message body (no timestamp/tag prefix),
    # then extract lines between the JSON markers.
    $ADB_CMD logcat -d -v raw -s QCBenchmark 2>/dev/null \
        | awk '/BENCHMARK_RESULTS_JSON_START/{flag=1; next} /BENCHMARK_RESULTS_JSON_END/{flag=0} flag' \
        > "$OUTPUT"
}

log "Results written to: $OUTPUT"

# Print summary
if command -v python3 &>/dev/null; then
    python3 - <<'PYEOF' "$OUTPUT"
import json, sys
with open(sys.argv[1]) as f:
    r = json.load(f)
if "error" in r:
    print(f"BENCHMARK FAILED: {r['error']}")
    sys.exit(1)
stub = r.get('stub_mode', False)
print("=" * 60)
if stub:
    print("BENCHMARK SUMMARY  [STUB MODE — MNN AAR not integrated]")
else:
    print("BENCHMARK SUMMARY")
print("=" * 60)
print(f"  Model:              {r.get('model_name','?')}")
print(f"  Device:             {r.get('device_model','?')}")
print(f"  Android version:    {r.get('android_version','?')}")
print(f"  Total RAM:          {r.get('total_ram_mb','?')} MB")
print(f"  CPU-only mode:      {r.get('cpu_only','?')}")
print(f"  Stub mode:          {stub}")
print(f"  Model load time:    {r.get('model_load_time_ms','?')} ms")
print(f"  Iterations:         {r.get('iterations','?')}")
print(f"  Errors:             {r.get('error_count','?')}")
print(f"  p50 latency:        {r.get('p50_latency_ms','?')} ms")
print(f"  p95 latency:        {r.get('p95_latency_ms','?')} ms  (budget: ≤10000 ms)")
print(f"  Peak memory:        {r.get('peak_memory_mb','?')} MB  (budget: ≤6144 MB)")
print(f"  Budget met (10s):   {r.get('budget_met_10s','?')}")
print(f"  Timestamp:          {r.get('timestamp_utc','?')}")
print("=" * 60)
if stub:
    print("WARNING: STUB MODE — latencies are simulated (2–4.5 s/iter), NOT real MNN numbers.")
    print("  Next step: add MNN-android.aar to build.gradle.kts and wire nativeRunInference().")
budget_ok = r.get('budget_met_10s', False)
if budget_ok:
    suffix = " (simulated)" if stub else ""
    print(f"PASS: p95 latency within 10 s budget{suffix}.")
else:
    p95 = r.get('p95_latency_ms', '?')
    print(f"FAIL: p95 latency {p95} ms exceeds 10 s budget — model or hardware tuning needed.")
    sys.exit(2)
PYEOF
else
    log "python3 not found — raw results in $OUTPUT"
    cat "$OUTPUT"
fi
