#!/usr/bin/env bash
#
# qc-probe.sh — VLM validation harness for QC inspection.
#
# Reusable. The API key and the sample images are supplied at invocation and
# are never written to disk, never logged, and never committed.
#
#   ./qc-probe.sh probe  --api-key-file ~/.bailian.key --images ./samples/images
#   ./qc-probe.sh sweep  --api-key-file ~/.bailian.key --image ./samples/images/ref_front.jpg
#   ./qc-probe.sh run    --api-key-file ~/.bailian.key --images ./samples/images --phase 1
#   ./qc-probe.sh score  --run 20260726-142230
#
# Dependencies: bash 4+, curl, jq, python3 (estimator + scorer). Pillow is
# needed only by lib/estimator.py's file-reading path (probe/sweep/run).
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Globals. BASE_URL is region- and workspace-specific: never hardcode it here.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${BAILIAN_BASE_URL:-}"
API_KEY=""                      # populated at runtime, never persisted
IMAGES_DIR=""
SINGLE_IMAGE=""
PHASE="1"
RESULTS_ROOT="${SCRIPT_DIR}/results"
RUN_ID=""
CONCURRENCY=4
TIMEOUT=120
FORCE=0
MAX_RETRIES=3

# Phase 1+ matrix flags (single model under test; see PRD §5). Defaults are
# the Phase 1 "chosen config": full-resolution default, three angles, the
# structured-json prompt.
RUN_MAX_PIXELS="default"
RUN_N_IMAGES=3
RUN_PROMPT="v2_structured_json"

PROMPT_PROBE="Describe this image in one sentence."

# Single model under test this round (PRD v2 §5: "Matrix dimensions ... Single
# model under test: qwen3-vl-235b-a22b-instruct"). Every other candidate --
# qwen3-vl-plus, qwen-vl-max, qwen3.7-plus, the -thinking variant, the local
# 30B control -- is explicitly out of scope for Phase 1+ this round.
RUN_MODEL="qwen3-vl-235b-a22b-instruct"
RUN_MODEL_TOKEN_PIXELS=1024
RUN_MODEL_DEFAULT_MAX_PIXELS=2621440

# Phase 0 (A1) capability probe candidates ONLY. Per PRD v2 §A1: probe the
# -instruct and -thinking variants plus the bare alias (expected BLOCKED,
# confirms the alias does not resolve). Do NOT probe qwen3-vl-plus,
# qwen-vl-max, or qwen3.7-plus -- they are out of scope for this round and
# probing them invites the matrix to creep back open.
#
#   id | expect_vision | token_pixels | thinking_mode | default_max_pixels
PROBE_MODELS=(
  "qwen3-vl-235b-a22b-instruct|unknown|1024|na|2621440"
  "qwen3-vl-235b-a22b-thinking|unknown|1024|forced|2621440"
  "qwen3-vl-235b-a22b|no|1024|na|2621440"
)

MAX_PIXELS_SWEEP=(2621440 1310720 5242880 HIGHRES)

# ---------------------------------------------------------------------------
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warn: %s\n' "$*" >&2; }
log()  { printf '%s\n' "$*" >&2; }

need() { command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1"; }

# base64 and date differ between GNU and BSD userland. Detect, do not guess.
detect_platform() {
  if base64 --help 2>&1 | grep -q -- '-w'; then B64="base64 -w0"; else B64="base64"; fi
  if date +%s%N 2>/dev/null | grep -qE '^[0-9]{19}$'; then HAVE_NS=1; else HAVE_NS=0; fi
}

now_ms() {
  if [[ $HAVE_NS -eq 1 ]]; then echo $(( $(date +%s%N) / 1000000 ));
  else python3 -c 'import time;print(int(time.time()*1000))'; fi
}

# ---------------------------------------------------------------------------
# Credential intake. The only three accepted paths. Never a positional arg.
# ---------------------------------------------------------------------------
read_api_key() {
  local src="$1" val="$2"
  set +x                                    # never leak the key under trace
  case "$src" in
    file)
      [[ -f "$val" ]] || die "key file not found: $val"
      # Refuse a key stored inside the repo tree.
      local abs repo
      abs="$(cd "$(dirname "$val")" && pwd)/$(basename "$val")"
      repo="$SCRIPT_DIR"
      [[ "$abs" == "$repo"/* ]] && die "refusing to read a key from inside the repo tree"
      API_KEY="$(tr -d '[:space:]' < "$val")"
      ;;
    arg)
      API_KEY="$val"
      warn "--api-key exposes the key in shell history; prefer --api-key-file"
      ;;
    prompt)
      read -r -s -p "Bailian API key: " API_KEY < /dev/tty
      echo >&2
      ;;
  esac
  [[ -n "$API_KEY" ]] || die "empty API key"
  [[ "$API_KEY" == sk-* ]] || warn "key does not start with 'sk-'; continuing anyway"
}

# ---------------------------------------------------------------------------
# A2 — local token estimator. Delegates to lib/estimator.py: one
# implementation, directly unit-tested (tests/test_estimator.py), instead of
# duplicating the smart_resize arithmetic in a shell heredoc.
# Prints: tokens h_bar w_bar
# ---------------------------------------------------------------------------
estimate_tokens() {
  local img="$1" token_pixels="${2:-1024}" max_pixels="${3:-2621440}" highres="${4:-0}"
  local extra_flag=()
  [[ "$highres" == "1" ]] && extra_flag=(--high-resolution)
  python3 "${SCRIPT_DIR}/lib/estimator.py" \
    --image "$img" --token-pixels "$token_pixels" --max-pixels "$max_pixels" \
    "${extra_flag[@]}"
}

# ---------------------------------------------------------------------------
# Build the messages payload. Accepts 1..N image paths plus a prompt.
# ---------------------------------------------------------------------------
build_payload() {
  local model="$1" prompt="$2" thinking="$3" max_pixels="$4"; shift 4
  local imgs=("$@")

  local content_file; content_file="$(mktemp)"
  echo '[]' > "$content_file"
  for img in "${imgs[@]}"; do
    local mime b64
    case "${img##*.}" in
      jpg|jpeg|JPG|JPEG) mime="image/jpeg" ;;
      png|PNG)           mime="image/png"  ;;
      webp|WEBP)         mime="image/webp" ;;
      *) die "unsupported image type: $img" ;;
    esac
    # The base64 blob must never be passed as a jq command-line argument:
    # Linux caps a single execve() argument at MAX_ARG_STRLEN (128 KiB), and
    # any real photo's base64 encoding clears that easily. Route it through
    # --rawfile instead, which reads the file's bytes directly.
    b64="$($B64 < "$img")"
    local b64_file; b64_file="$(mktemp)"
    printf '%s' "$b64" > "$b64_file"
    jq --arg mime "$mime" --rawfile b64 "$b64_file" \
       '. += [{"type":"image_url","image_url":{"url":("data:" + $mime + ";base64," + $b64)}}]' \
       "$content_file" > "${content_file}.n" && mv "${content_file}.n" "$content_file"
    rm -f "$b64_file"
  done
  jq --arg t "$prompt" '. += [{"type":"text","text":$t}]' \
     "$content_file" > "${content_file}.n" && mv "${content_file}.n" "$content_file"

  # enable_thinking is set explicitly whenever the model actually has the
  # toggle. "na" (no toggle at all, e.g. -instruct) and "forced" (toggle
  # exists but cannot be disabled, e.g. -thinking) both OMIT the parameter
  # entirely -- sending `false` to a model with no toggle would misrepresent
  # a config axis that was never actually exercised (PRD §5: "record the
  # omission ... so a later reader does not assume thinking was tested and
  # found unhelpful").
  local extra='{}'
  if [[ "$thinking" == "true" ]]; then
    extra='{"enable_thinking":true,"thinking_budget":2048}'
  elif [[ "$thinking" == "false" ]]; then
    extra='{"enable_thinking":false}'
  fi
  if [[ "$max_pixels" == "HIGHRES" ]]; then
    extra="$(echo "$extra" | jq '. + {"vl_high_resolution_images":true}')"
  fi

  jq -n --arg m "$model" --slurpfile c "$content_file" --argjson e "$extra" \
     '{model:$m, messages:[{role:"user", content:$c[0]}], max_tokens:1024} + $e'
  rm -f "$content_file"
}

# ---------------------------------------------------------------------------
# Single call with retry. Persists the raw response; never persists the key.
# ---------------------------------------------------------------------------
call_api() {
  local payload_file="$1" out_file="$2"
  local attempt=0 http t0 t1 wait_total=0

  while (( attempt < MAX_RETRIES )); do
    t0="$(now_ms)"
    http="$(curl -sS -o "$out_file" -w '%{http_code}' \
      --max-time "$TIMEOUT" \
      -H "Authorization: Bearer ${API_KEY}" \
      -H "Content-Type: application/json" \
      -X POST "${BASE_URL}/chat/completions" \
      --data-binary "@${payload_file}" 2>>"${out_file}.err" || echo 000)"
    t1="$(now_ms)"
    echo $(( t1 - t0 )) > "${out_file}.request_ms"
    echo "$attempt" > "${out_file}.retries"

    case "$http" in
      429|5??|000)
        attempt=$(( attempt + 1 ))
        local backoff=$(( 2 ** attempt ))
        wait_total=$(( wait_total + backoff * 1000 ))
        sleep "$backoff"
        ;;
      *) echo "$wait_total" > "${out_file}.wait_ms"; echo "$http"; return 0 ;;
    esac
  done
  echo "$wait_total" > "${out_file}.wait_ms"
  echo "$http"
}

# usage extraction tolerant of both the flat and the details-block shape
extract_usage() {
  jq -r '
    (.usage.prompt_tokens      // "null") as $in  |
    (.usage.completion_tokens  // "null") as $out |
    (.usage.image_tokens // .usage.prompt_tokens_details.image_tokens // "null") as $img |
    (.error.code // .code // "null") as $err |
    "\($in)\t\($out)\t\($img)\t\($err)"' "$1" 2>/dev/null || echo "null	null	null	parse_error"
}

# ---------------------------------------------------------------------------
# Phase 0 — A1 model ID resolution and capability probe.
# ---------------------------------------------------------------------------
cmd_probe() {
  local img="${SINGLE_IMAGE:-$(find "$IMAGES_DIR" -type f \( -name '*.jpg' -o -name '*.png' \) | head -1)}"
  [[ -n "$img" && -f "$img" ]] || die "no probe image found"

  local dims; dims="$(python3 -c "from PIL import Image;i=Image.open('$img');print(i.width,i.height)")"
  log "probe image: $(basename "$img")  ${dims// /x}"
  echo

  printf '%-32s %-8s %-6s %8s %8s %8s %8s  %s\n' \
    MODEL EXPECT IMG? IMG_TOK EST DEV% MS NOTE
  printf '%s\n' "$(printf '%.0s-' {1..110})"

  local outdir="${RESULTS_ROOT}/probe-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$outdir"

  for spec in "${PROBE_MODELS[@]}"; do
    IFS='|' read -r id expect tok_px thinking def_px <<< "$spec"
    read -r est _h _w <<< "$(estimate_tokens "$img" "$tok_px" "$def_px" 0)"

    local pf rf; pf="$(mktemp)"; rf="${outdir}/${id}.json"
    build_payload "$id" "$PROMPT_PROBE" "$thinking" "default" "$img" > "$pf"
    local http; http="$(call_api "$pf" "$rf")"
    rm -f "$pf"

    local ms; ms="$(cat "${rf}.request_ms" 2>/dev/null || echo -)"
    IFS=$'\t' read -r in_tok out_tok img_tok err <<< "$(extract_usage "$rf")"

    local verdict note dev
    if [[ "$http" == "404" || "$err" == *"NotFound"* || "$err" == *"not_found"* || "$err" == *"InvalidParameter"* ]]; then
      verdict="BLOCKED"; note="HTTP ${http} ${err}"
    elif [[ "$http" != "200" ]]; then
      verdict="ERR"; note="HTTP ${http} ${err}"
    elif [[ "$img_tok" != "null" && "$img_tok" -gt 0 ]]; then
      verdict="YES"; note="ok"
    elif [[ "$in_tok" != "null" && "$in_tok" -gt 200 ]]; then
      verdict="YES"; note="inferred from input_tokens"
    else
      verdict="NO"; note="no image tokens billed"
    fi

    if [[ "$img_tok" != "null" && "$img_tok" -gt 0 ]]; then
      dev="$(python3 -c "print(round(100*($est-$img_tok)/$img_tok,2))")"
    else dev="-"; fi

    printf '%-32s %-8s %-6s %8s %8s %8s %8s  %s\n' \
      "$id" "$expect" "$verdict" "${img_tok}" "$est" "$dev" "$ms" "${note:0:40}"
  done

  echo
  log "raw responses: $outdir"
  log "A1 verdict: qwen3-vl-235b-a22b-instruct/-thinking reading YES are callable."
  log "            the bare alias qwen3-vl-235b-a22b is expected BLOCKED/ERR --"
  log "            that confirms the ID convention, not a probe failure."
}

# ---------------------------------------------------------------------------
# Phase 0b — max_pixels sweep. Not optional: the default differs by model
# family and a silently downscaled frame invalidates every accuracy number
# downstream. Sweeps the single model under test (RUN_MODEL) unless --model
# overrides it, e.g. to double-check a probe candidate before it is dropped.
# ---------------------------------------------------------------------------
cmd_sweep() {
  local img="${SINGLE_IMAGE:-$(find "$IMAGES_DIR" -type f \( -name '*.jpg' -o -name '*.png' \) | head -1)}"
  [[ -n "$img" && -f "$img" ]] || die "no image supplied; use --image"

  local model="${SWEEP_MODEL:-$RUN_MODEL}"
  log "sweep model: $model   image: $(basename "$img")"
  echo
  printf '%-12s %8s %8s %14s %8s\n' MAX_PIXELS IMG_TOK EST EFFECTIVE_WH MS
  printf '%s\n' "$(printf '%.0s-' {1..56})"

  local outdir="${RESULTS_ROOT}/sweep-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$outdir"

  for mp in "${MAX_PIXELS_SWEEP[@]}"; do
    local hi=0 mpx=$mp
    [[ "$mp" == "HIGHRES" ]] && { hi=1; mpx=2621440; }
    read -r est h w <<< "$(estimate_tokens "$img" "$RUN_MODEL_TOKEN_PIXELS" "$mpx" "$hi")"

    local pf rf; pf="$(mktemp)"; rf="${outdir}/mp-${mp}.json"
    build_payload "$model" "$PROMPT_PROBE" "na" "$mp" "$img" > "$pf"
    call_api "$pf" "$rf" >/dev/null; rm -f "$pf"

    IFS=$'\t' read -r _in _out img_tok _err <<< "$(extract_usage "$rf")"
    printf '%-12s %8s %8s %14s %8s\n' \
      "$mp" "$img_tok" "$est" "${w}x${h}" "$(cat "${rf}.request_ms" 2>/dev/null || echo -)"
  done

  echo
  log "Compare EFFECTIVE_WH against the source resolution. Any row smaller than"
  log "the original means pixels were discarded before the model ever saw them."
}

# ---------------------------------------------------------------------------
# Phase 1+ — full sample run against the single model under test, at one
# (max_pixels, n_images, prompt) configuration per invocation. Resumable; raw
# first, scoring separate. Give each phase/ablation its own --run id so
# results never collide -- comparing configs means diffing report.md across
# run ids, not re-running the same run id with different flags.
#
# n_images=1 runs each angle of a sample SEPARATELY (PRD §A5: "so the
# comparison is not confounded by which angle was chosen"), recorded as
# distinct cells named "<model>-angle<N>" so lib/score.py's per-model
# grouping reports each angle's accuracy independently.
# ---------------------------------------------------------------------------
cmd_run() {
  [[ -d "$IMAGES_DIR" ]] || die "--images directory required"
  RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
  local outdir="${RESULTS_ROOT}/${RUN_ID}/raw"; mkdir -p "$outdir"
  log "run_id=${RUN_ID}  phase=${PHASE}  model=${RUN_MODEL}"
  log "config: max_pixels=${RUN_MAX_PIXELS}  n_images=${RUN_N_IMAGES}  prompt=${RUN_PROMPT}"

  local prompt_file="${SCRIPT_DIR}/prompts/${RUN_PROMPT}.txt"
  [[ -f "$prompt_file" ]] || die "prompt file not found: $prompt_file"
  local prompt; prompt="$(cat "$prompt_file")"

  local hi=0 mpx="$RUN_MAX_PIXELS"
  if [[ "$RUN_MAX_PIXELS" == "HIGHRES" ]]; then hi=1; mpx="$RUN_MODEL_DEFAULT_MAX_PIXELS";
  elif [[ "$RUN_MAX_PIXELS" == "default" ]]; then mpx="$RUN_MODEL_DEFAULT_MAX_PIXELS"; fi

  local jobs=0

  for sample_dir in "$IMAGES_DIR"/*/; do
    local sid; sid="$(basename "$sample_dir")"
    mapfile -t imgs < <(find "$sample_dir" -type f \( -name '*.jpg' -o -name '*.png' \) | sort)
    (( ${#imgs[@]} )) || { warn "no images in $sid"; continue; }

    if [[ "$RUN_N_IMAGES" == "1" ]]; then
      # One cell per angle, run independently -- never averaged together.
      local idx=0
      for one_img in "${imgs[@]}"; do
        local cell_model="${RUN_MODEL}-angle${idx}"
        local cell="${outdir}/${sid}__${cell_model}.json"
        if [[ ! -f "$cell" || $FORCE -eq 1 ]]; then
          (
            local pf; pf="$(mktemp)"
            build_payload "$RUN_MODEL" "$prompt" "na" "$RUN_MAX_PIXELS" "$one_img" > "$pf"
            call_api "$pf" "$cell" >/dev/null
            rm -f "$pf"
          ) &
          jobs=$(( jobs + 1 ))
          (( jobs % CONCURRENCY == 0 )) && wait
        fi
        idx=$(( idx + 1 ))
      done
    else
      local cell="${outdir}/${sid}__${RUN_MODEL}.json"
      if [[ ! -f "$cell" || $FORCE -eq 1 ]]; then
        (
          local pf; pf="$(mktemp)"
          build_payload "$RUN_MODEL" "$prompt" "na" "$RUN_MAX_PIXELS" "${imgs[@]}" > "$pf"
          call_api "$pf" "$cell" >/dev/null
          rm -f "$pf"
        ) &
        jobs=$(( jobs + 1 ))
        (( jobs % CONCURRENCY == 0 )) && wait
      fi
    fi
  done
  wait

  # elapsed_ms = encode + request + retry backoff, the figure the operator
  # actually experiences (PRD §4). encode_ms is not separately instrumented
  # here (base64 encoding happens inline in build_payload); record 0 rather
  # than fabricate a number, and let elapsed = request + wait.
  for f in "$outdir"/*.request_ms; do
    [[ -f "$f" ]] || continue
    local base="${f%.request_ms}"
    local req wait_ms
    req="$(cat "$f" 2>/dev/null || echo 0)"
    wait_ms="$(cat "${base}.wait_ms" 2>/dev/null || echo 0)"
    echo 0 > "${base}.encode_ms"
    echo $(( req + wait_ms )) > "${base}.elapsed_ms"
  done

  log "raw written: ${outdir}"
  log "now: ./qc-probe.sh score --run ${RUN_ID}"
}

# ---------------------------------------------------------------------------
# Scoring — offline, zero API calls, re-runnable.
# ---------------------------------------------------------------------------
cmd_score() {
  [[ -n "$RUN_ID" ]] || die "--run <run_id> required"
  local raw="${RESULTS_ROOT}/${RUN_ID}/raw"
  [[ -d "$raw" ]] || die "no raw directory for run ${RUN_ID}"
  [[ -f "${SCRIPT_DIR}/samples/ground_truth.jsonl" ]] || die "samples/ground_truth.jsonl not found"
  [[ -f "${SCRIPT_DIR}/config/gates.env" ]] || die "config/gates.env missing; refusing to invent thresholds"

  log "scoring ${RUN_ID} from ${raw} (no API calls)"
  python3 "${SCRIPT_DIR}/lib/score.py" --raw "$raw" \
    --ground-truth "${SCRIPT_DIR}/samples/ground_truth.jsonl" \
    --models "${SCRIPT_DIR}/config/models.tsv" \
    --gates "${SCRIPT_DIR}/config/gates.env" \
    --out "${RESULTS_ROOT}/${RUN_ID}"
}

# ---------------------------------------------------------------------------
usage() {
  sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Subcommands:
  probe    Phase 0  — resolve model IDs, confirm image input is accepted (A1)
  sweep    Phase 0b — max_pixels sweep, expose silent downscaling (A6)
  run      Phase 1+ — full sample set at one config, raw responses only
  score    Offline scoring and report generation, zero API calls

Credentials (pick one; --api-key-file preferred):
  --api-key-file PATH   read the key from a file outside the repo tree
  --api-key VALUE       exposed in shell history; prefix the command with a space
  (omit both)           interactive prompt, echo disabled

Options:
  --images DIR       sample root; run expects DIR/<sample_id>/*.jpg
  --image PATH       single image, for probe and sweep
  --phase N          default 1 (label only; run behaviour is set by the flags below)
  --run ID           run id; for score, and to resume/label a run
  --model ID         sweep only: override the model under test
  --max-pixels V      run only: "default" | integer | HIGHRES  (default: default)
  --n-images N        run only: 1 | 3                          (default: 3)
  --prompt NAME       run only: prompt file stem under prompts/ (default: v2_structured_json)
  --concurrency N     default 4
  --force             re-run cells that already have raw output
  --base-url URL      overrides BAILIAN_BASE_URL
  --timeout SECONDS   per-request curl timeout, default 120

The API key and the sample images are supplied at run time. Neither is written
to disk by this script, and neither belongs in the repository.

To keep the key out of shell history when using --api-key: prefix the command
with a space (HISTCONTROL=ignorespace), or use --api-key-file instead.
EOF
}

# ---------------------------------------------------------------------------
main() {
  need curl; need jq; need python3
  detect_platform

  local cmd="${1:-}"; shift || true
  [[ -n "$cmd" ]] || { usage; exit 1; }
  case "$cmd" in -h|--help|help) usage; exit 0 ;; esac

  local key_src="prompt" key_val=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --api-key)      key_src="arg";  key_val="$2"; shift 2 ;;
      --api-key-file) key_src="file"; key_val="$2"; shift 2 ;;
      --images)       IMAGES_DIR="$2"; shift 2 ;;
      --image)        SINGLE_IMAGE="$2"; shift 2 ;;
      --phase)        PHASE="$2"; shift 2 ;;
      --run)          RUN_ID="$2"; shift 2 ;;
      --model)        SWEEP_MODEL="$2"; shift 2 ;;
      --max-pixels)   RUN_MAX_PIXELS="$2"; shift 2 ;;
      --n-images)     RUN_N_IMAGES="$2"; shift 2 ;;
      --prompt)       RUN_PROMPT="$2"; shift 2 ;;
      --concurrency)  CONCURRENCY="$2"; shift 2 ;;
      --timeout)      TIMEOUT="$2"; shift 2 ;;
      --base-url)     BASE_URL="$2"; shift 2 ;;
      --force)        FORCE=1; shift ;;
      *) die "unknown option: $1" ;;
    esac
  done

  if [[ "$cmd" != "score" ]]; then
    [[ -n "$BASE_URL" ]] || die "BAILIAN_BASE_URL not set (region- and workspace-specific; do not commit it)"
    read_api_key "$key_src" "$key_val"
  fi

  case "$cmd" in
    probe) cmd_probe ;;
    sweep) cmd_sweep ;;
    run)   cmd_run ;;
    score) cmd_score ;;
    *) die "unknown subcommand: $cmd" ;;
  esac
}

main "$@"
