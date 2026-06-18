#!/usr/bin/env bash
# §4.3.0 On-device MNN benchmark runner.
# Target device: Snapdragon 8 Gen, 8 GB RAM, 128 GB storage.
# Default model: Qwen2-VL-2B-Instruct-MNN (INT4) — viable on 8 GB RAM.
#
# Usage:
#   ./scripts/benchmark_mnn.sh [OPTIONS]
#
# Options:
#   -d DEVICE    ADB device serial (default: first connected)
#   -p MODEL_PATH  Path on device to model dir (default: /sdcard/qwen_2b_mnn)
#   -i ITERATIONS  Number of inference iterations (default: 10)
#   -m MODEL_NAME  Model name label (default: Qwen2-VL-2B-Instruct-MNN)
#   -o OUTPUT      Local output file for JSON results (default: benchmark_results.json)
#   -h             Show this help
#
# Prerequisites:
#   - ADB in PATH and device connected with USB debugging enabled
#   - APK installed: adb install app/build/outputs/apk/debug/app-debug.apk
#   - Model provisioned to device: adb push <model_dir> /sdcard/qwen_2b_mnn/
#
# Budget targets (§4.3.0):
#   - Cold start load:  ≤ 30 s
#   - p95 per-image:    ≤ 10 s
#   - Peak memory:      ≤ 6 GB (leaves 2 GB headroom on 8 GB device)

set -euo pipefail

DEVICE=""
MODEL_PATH="/sdcard/qwen_2b_mnn"
ITERATIONS=10
MODEL_NAME="Qwen2-VL-2B-Instruct-MNN"
OUTPUT="benchmark_results.json"
PACKAGE="com.giraffetechnology.qc"
ACTIVITY=".benchmark.BenchmarkActivity"
DEVICE_OUTPUT="/sdcard/qc_benchmark_results.json"

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while getopts "d:p:i:m:o:h" opt; do
    case $opt in
        d) DEVICE="$OPTARG" ;;
        p) MODEL_PATH="$OPTARG" ;;
        i) ITERATIONS="$OPTARG" ;;
        m) MODEL_NAME="$OPTARG" ;;
        o) OUTPUT="$OPTARG" ;;
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

# Verify APK installed
if ! $ADB_CMD shell pm list packages 2>/dev/null | grep -q "$PACKAGE"; then
    echo "ERROR: APK not installed. Run:" >&2
    echo "  adb install app/build/outputs/apk/debug/app-debug.apk" >&2
    exit 1
fi

# Verify model directory exists on device
if ! $ADB_CMD shell test -d "$MODEL_PATH" 2>/dev/null; then
    echo "ERROR: Model directory not found on device at: $MODEL_PATH" >&2
    echo "Provision the model first:" >&2
    echo "  adb push <local_model_dir>/ $MODEL_PATH/" >&2
    echo "  See docs/DEPLOYMENT_LOCAL_QWEN.md for full instructions." >&2
    exit 1
fi

log "Starting BenchmarkActivity..."
log "  model_path=$MODEL_PATH  iterations=$ITERATIONS  model_name=$MODEL_NAME"

$ADB_CMD shell am start -n "${PACKAGE}/${ACTIVITY}" \
    --es model_path "$MODEL_PATH" \
    --ei iterations "$ITERATIONS" \
    --es model_name "$MODEL_NAME"

# Wait for benchmark to finish (poll logcat for completion marker)
log "Waiting for benchmark to complete (up to 5 min)..."
TIMEOUT=300
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
    # Fallback: extract JSON from logcat between markers
    $ADB_CMD logcat -d -s QCBenchmark 2>/dev/null \
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
print("=" * 60)
print("BENCHMARK SUMMARY")
print("=" * 60)
print(f"  Model:              {r.get('model_name','?')}")
print(f"  Device:             {r.get('device_model','?')}")
print(f"  Android version:    {r.get('android_version','?')}")
print(f"  Total RAM:          {r.get('total_ram_mb','?')} MB")
print(f"  Model load time:    {r.get('model_load_time_ms','?')} ms")
print(f"  Iterations:         {r.get('iterations','?')}")
print(f"  Errors:             {r.get('error_count','?')}")
print(f"  p50 latency:        {r.get('p50_latency_ms','?')} ms")
print(f"  p95 latency:        {r.get('p95_latency_ms','?')} ms  (budget: ≤10000 ms)")
print(f"  Peak memory:        {r.get('peak_memory_mb','?')} MB  (budget: ≤6144 MB)")
print(f"  Budget met (10s):   {r.get('budget_met_10s','?')}")
print(f"  Timestamp:          {r.get('timestamp_utc','?')}")
print("=" * 60)
budget_ok = r.get('budget_met_10s', False)
if budget_ok:
    print("PASS: p95 latency within 10 s budget.")
else:
    p95 = r.get('p95_latency_ms', '?')
    print(f"FAIL: p95 latency {p95} ms exceeds 10 s budget — model or hardware tuning needed.")
    sys.exit(2)
PYEOF
else
    log "python3 not found — raw results in $OUTPUT"
    cat "$OUTPUT"
fi
