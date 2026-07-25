#!/usr/bin/env python3
"""
lib/score.py — offline scorer for qc-probe.sh.

Reads raw API responses already on disk and emits report.json + report.md.
Makes ZERO API calls: scoring is re-runnable without spending money, and a
scoring bug never costs a second run.

Invoked by:
    ./qc-probe.sh score --run <run_id>

Directly:
    python3 lib/score.py \
        --raw results/<run_id>/raw \
        --ground-truth samples/ground_truth.jsonl \
        --models config/models.tsv \
        --gates config/gates.env \
        --out results/<run_id>

Standard library plus nothing. No numpy, no scipy — this must run on the
inspection host without a package install.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path

Z95 = 1.959963984540054

# Below this many samples, no accuracy claim is reportable. Four samples
# cannot distinguish a good model from a lucky one; prior rounds reached a
# no-go verdict on roughly that many.
MIN_N_FOR_CLAIM = 30

COUNT_FIELDS = ("petals", "pearls", "rhinestones")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    """Wilson score interval. Returns (point, low, high) as fractions.

    Preferred over the normal approximation because it stays inside [0,1] and
    behaves at the small n this project actually has.
    """
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, max(0.0, centre - margin), min(1.0, centre + margin))


def pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile. Mean latency hides the tail that breaks an SLO."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return s[k]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
@dataclass
class ModelSpec:
    model_id: str
    input_tiers: list[tuple[int, float]]   # [(min_input_tokens, cny_per_m), ...]
    output_tiers: list[tuple[int, float]]
    token_pixels: int
    default_max_pixels: int
    thinking: str


def parse_price(cell: str, model_id: str, kind: str) -> list[tuple[int, float]]:
    """Accept a scalar '12.0' or a tier spec '0:2.0,256000:6.0'.

    TBD is fatal. A guessed unit price silently corrupts every cost number in
    the report, and a wrong cost figure is worse than a missing one.
    """
    cell = cell.strip()
    if cell.upper() == "TBD" or not cell:
        raise SystemExit(
            f"fatal: {kind} price for '{model_id}' is TBD in models.tsv.\n"
            f"       Pull the current unit price from the Bailian console.\n"
            f"       Refusing to substitute a guess."
        )
    tiers: list[tuple[int, float]] = []
    if ":" in cell:
        for part in cell.split(","):
            lo, price = part.split(":")
            tiers.append((int(lo), float(price)))
    else:
        tiers.append((0, float(cell)))
    return sorted(tiers)


def load_models(path: Path) -> dict[str, ModelSpec]:
    specs: dict[str, ModelSpec] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = re.split(r"\s+", line)
        if len(cols) < 7:
            raise SystemExit(f"fatal: malformed models.tsv row: {line}")
        mid, in_p, out_p, _tiered, _vision, tok_px, max_px = cols[:7]
        thinking = cols[7] if len(cols) > 7 else "optional"
        specs[mid] = ModelSpec(
            model_id=mid,
            input_tiers=parse_price(in_p, mid, "input"),
            output_tiers=parse_price(out_p, mid, "output"),
            token_pixels=int(tok_px),
            default_max_pixels=int(max_px),
            thinking=thinking,
        )
    return specs


def load_gates(path: Path) -> dict[str, float | None]:
    gates: dict[str, float | None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        gates[k.strip()] = None if v in ("", "null", "TBD") else float(v)
    return gates


def tier_rate(tiers: list[tuple[int, float]], input_tokens: int) -> float:
    """Bailian tiering: the tier is chosen by the request's total input token
    count, and ALL tokens in that request bill at that tier's rate -- not just
    the tokens above the threshold. A linear model understates high-resolution
    runs badly.
    """
    rate = tiers[0][1]
    for lo, r in tiers:
        if input_tokens >= lo:
            rate = r
    return rate


# ---------------------------------------------------------------------------
# Raw response parsing
# ---------------------------------------------------------------------------
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def extract_model_json(raw: dict) -> tuple[dict | None, str | None]:
    """Pull the model's structured verdict out of an OpenAI-compatible reply."""
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None, "no_content"
    if not isinstance(content, str):
        # DashScope multimodal shape: content may be a list of parts.
        try:
            content = "".join(p.get("text", "") for p in content)
        except Exception:  # noqa: BLE001
            return None, "unreadable_content"
    cleaned = FENCE.sub("", content).strip()
    # Tolerate prose wrapped around the JSON object.
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        return None, "no_json_object"
    try:
        return json.loads(cleaned[start:end + 1]), None
    except json.JSONDecodeError as exc:
        return None, f"json_decode:{exc.msg}"


@dataclass
class Row:
    sample_id: str
    model_id: str
    parse_ok: bool = False
    error: str | None = None
    http_error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    image_tokens: int | None = None
    encode_ms: int | None = None
    request_ms: int | None = None
    retry_wait_ms: int | None = None
    elapsed_ms: int | None = None       # what the operator experiences
    retries: int = 0
    cost_cny: float | None = None
    predicted: dict = field(default_factory=dict)
    truth: dict = field(default_factory=dict)
    counts_correct: dict = field(default_factory=dict)
    verdict_correct: bool | None = None
    false_accept: bool = False
    false_reject: bool = False
    flagged: bool = False


def read_side_file(path: Path, default):
    try:
        return type(default)(path.read_text().strip())
    except Exception:  # noqa: BLE001
        return default


def build_rows(raw_dir: Path, truth: dict[str, dict],
               specs: dict[str, ModelSpec]) -> list[Row]:
    rows: list[Row] = []
    for f in sorted(raw_dir.glob("*.json")):
        stem = f.stem
        if "__" not in stem:
            continue
        sample_id, model_id = stem.split("__", 1)
        row = Row(sample_id=sample_id, model_id=model_id)
        base = str(f)
        row.encode_ms = read_side_file(Path(base + ".encode_ms"), 0)
        row.request_ms = read_side_file(Path(base + ".request_ms"), 0) or None
        row.retry_wait_ms = read_side_file(Path(base + ".wait_ms"), 0)
        row.elapsed_ms = read_side_file(Path(base + ".elapsed_ms"), 0) or None
        row.retries = read_side_file(Path(base + ".retries"), 0)

        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            row.error = f"raw_unreadable:{exc}"
            rows.append(row)
            continue

        if isinstance(raw, dict) and ("error" in raw or "code" in raw):
            row.http_error = str(raw.get("code") or raw.get("error", {}).get("code"))

        usage = raw.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        row.input_tokens = usage.get("prompt_tokens")
        row.output_tokens = usage.get("completion_tokens")
        row.image_tokens = usage.get("image_tokens") or details.get("image_tokens")

        spec = specs.get(model_id)
        if spec and row.input_tokens is not None and row.output_tokens is not None:
            in_rate = tier_rate(spec.input_tiers, row.input_tokens)
            out_rate = tier_rate(spec.output_tiers, row.input_tokens)
            row.cost_cny = (row.input_tokens * in_rate
                            + row.output_tokens * out_rate) / 1_000_000

        pred, err = extract_model_json(raw)
        if pred is None:
            row.error = row.error or err
            rows.append(row)
            continue

        row.parse_ok = True
        row.predicted = pred
        gt = truth.get(sample_id)
        if gt is None:
            row.error = "no_ground_truth"
            rows.append(row)
            continue

        row.truth = gt
        for fld in COUNT_FIELDS:
            if fld in gt:
                row.counts_correct[fld] = (pred.get(fld) == gt.get(fld))

        pv, tv = pred.get("verdict"), gt.get("verdict")
        if pv in ("accept", "reject") and tv in ("accept", "reject"):
            row.verdict_correct = (pv == tv)
            row.false_accept = (tv == "reject" and pv == "accept")
            row.false_reject = (tv == "accept" and pv == "reject")

        row.flagged = bool(pred.get("needs_human_review"))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def summarise(rows: list[Row], gates: dict) -> dict:
    by_model: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_model[r.model_id].append(r)

    out = {}
    for model_id, rs in sorted(by_model.items()):
        scored = [r for r in rs if r.parse_ok and r.truth]
        n = len(scored)
        m: dict = {"n_cells": len(rs), "n_scored": n}

        m["parse_failure_rate"] = (
            sum(1 for r in rs if not r.parse_ok) / len(rs) if rs else None
        )
        m["error_count"] = sum(1 for r in rs if r.error or r.http_error)
        m["retry_count"] = sum(r.retries for r in rs)

        for fld in COUNT_FIELDS:
            hits = [r for r in scored if fld in r.counts_correct]
            ok = sum(1 for r in hits if r.counts_correct[fld])
            p, lo, hi = wilson(ok, len(hits))
            m[f"{fld}_accuracy"] = {
                "n": len(hits), "correct": ok,
                "point": p, "ci_low": lo, "ci_high": hi,
            }

        verdicts = [r for r in scored if r.verdict_correct is not None]
        ok = sum(1 for r in verdicts if r.verdict_correct)
        p, lo, hi = wilson(ok, len(verdicts))
        m["verdict_accuracy"] = {
            "n": len(verdicts), "correct": ok,
            "point": p, "ci_low": lo, "ci_high": hi,
        }

        # The two rates that actually drive the business decision.
        rejects = [r for r in verdicts if r.truth.get("verdict") == "reject"]
        accepts = [r for r in verdicts if r.truth.get("verdict") == "accept"]
        fa = sum(1 for r in rejects if r.false_accept)
        fr = sum(1 for r in accepts if r.false_reject)
        p, lo, hi = wilson(fa, len(rejects))
        m["false_accept_rate"] = {"n": len(rejects), "count": fa,
                                  "point": p, "ci_low": lo, "ci_high": hi}
        p, lo, hi = wilson(fr, len(accepts))
        m["false_reject_rate"] = {"n": len(accepts), "count": fr,
                                  "point": p, "ci_low": lo, "ci_high": hi}

        # SLO is gated on elapsed, not request time. A cell that succeeded on
        # the third attempt shows an acceptable request_ms and an elapsed_ms
        # several times larger; the operator waits for elapsed.
        elapsed = [float(r.elapsed_ms) for r in rs if r.elapsed_ms]
        request = [float(r.request_ms) for r in rs if r.request_ms]
        m["elapsed_ms"] = {
            "p50": percentile(elapsed, 0.50),
            "p95": percentile(elapsed, 0.95),
            "p99": percentile(elapsed, 0.99),
            "max": max(elapsed) if elapsed else None,
            "n": len(elapsed),
        }
        m["request_ms"] = {
            "p50": percentile(request, 0.50),
            "p95": percentile(request, 0.95),
            "n": len(request),
        }
        m["retry_wait_ms_total"] = sum(r.retry_wait_ms or 0 for r in rs)
        slo = gates.get("latency_p95_ms_max")
        p95 = m["elapsed_ms"]["p95"]
        m["slo_violation"] = (
            None if (slo is None or p95 is None) else bool(p95 > slo)
        )
        m["slo_violating_samples"] = (
            [] if slo is None
            else sorted(r.sample_id for r in rs if r.elapsed_ms and r.elapsed_ms > slo)
        )

        costs = [r.cost_cny for r in rs if r.cost_cny is not None]
        m["cost_cny"] = {
            "mean": statistics.fmean(costs) if costs else None,
            "p95": percentile(costs, 0.95),
            "total": sum(costs) if costs else None,
            "n": len(costs),
        }

        toks = [r.image_tokens for r in rs if r.image_tokens]
        m["image_tokens_mean"] = statistics.fmean(toks) if toks else None

        m["statistically_reportable"] = n >= MIN_N_FOR_CLAIM
        out[model_id] = m
    return out


def verdict_for(model_id: str, m: dict, gates: dict) -> str:
    """PASS / FAIL / INCONCLUSIVE. Never round INCONCLUSIVE toward PASS."""
    if not m["statistically_reportable"]:
        return "INCONCLUSIVE"
    fa_max = gates.get("false_accept_rate_max")
    fr_max = gates.get("false_reject_rate_max")
    if fa_max is None or fr_max is None:
        return "INCONCLUSIVE"          # thresholds unset: no verdict is possible
    fa, fr = m["false_accept_rate"], m["false_reject_rate"]
    if fa["n"] == 0 or fr["n"] == 0:
        return "INCONCLUSIVE"
    # Judge on the upper confidence bound, not the point estimate. A point
    # estimate that squeaks under a threshold on 30 samples is not evidence
    # the true rate is under it.
    return "PASS" if (fa["ci_high"] <= fa_max and fr["ci_high"] <= fr_max) else "FAIL"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def render_md(summary: dict, rows: list[Row], gates: dict, run_id: str) -> str:
    L: list[str] = []
    n_samples = len({r.sample_id for r in rows})
    L.append(f"# QC VLM Validation Report — `{run_id}`\n")
    L.append(f"- Samples: **{n_samples}**")
    L.append(f"- Models: **{len(summary)}**")
    L.append(f"- Cells: **{len(rows)}**\n")

    L.append("## Statistical power\n")
    if n_samples < MIN_N_FOR_CLAIM:
        L.append(
            f"> **WARNING — n={n_samples}, below the {MIN_N_FOR_CLAIM}-sample "
            f"floor.**\n>\n"
            f"> Every accuracy figure below is reported as `INCONCLUSIVE`. At "
            f"this sample size the confidence intervals span most of the "
            f"possible range, and a good model cannot be distinguished from a "
            f"lucky one. **Do not make a go/no-go decision from this run.**\n"
        )
    else:
        L.append(f"n={n_samples}, at or above the {MIN_N_FOR_CLAIM}-sample floor. "
                 f"Intervals below are Wilson score, 95%.\n")

    if gates.get("false_accept_rate_max") is None or gates.get("false_reject_rate_max") is None:
        L.append("> **Gate thresholds unset in `config/gates.env`.** Numbers are "
                 "reported; verdicts are withheld. Set the acceptable false-accept "
                 "and false-reject rates before reading this as a decision.\n")

    if len(summary) < 2:
        L.append("> **A4 (model scale is the missing variable): `DEFERRED`.** "
                 "This run contains a single model, so there is no ladder. This "
                 "round cannot distinguish 'needs a bigger model' from 'needs "
                 "better prompts or capture'.\n")

    L.append("> **Serving precision is not observable.** The no-quantization "
             "constraint applies to self-hosted inference only; what precision "
             "the API served is unknown and is not claimed here.\n")

    L.append("## Assumption verdicts\n")
    L.append("| Model | Verdict | Verdict acc. (95% CI) | False accept | False reject | n |")
    L.append("|---|---|---|---|---|---:|")
    for mid, m in summary.items():
        v = verdict_for(mid, m, gates)
        va, fa, fr = m["verdict_accuracy"], m["false_accept_rate"], m["false_reject_rate"]
        L.append(
            f"| `{mid}` | **{v}** | "
            f"{pct(va['point'])} [{pct(va['ci_low'])}–{pct(va['ci_high'])}] | "
            f"{pct(fa['point'])} (n={fa['n']}) | "
            f"{pct(fr['point'])} (n={fr['n']}) | {m['n_scored']} |"
        )

    L.append("\n## Counting accuracy\n")
    L.append("| Model | " + " | ".join(f.capitalize() for f in COUNT_FIELDS) + " |")
    L.append("|---|" + "---|" * len(COUNT_FIELDS))
    for mid, m in summary.items():
        cells = []
        for fld in COUNT_FIELDS:
            a = m[f"{fld}_accuracy"]
            cells.append(f"{pct(a['point'])} [{pct(a['ci_low'])}–{pct(a['ci_high'])}]")
        L.append(f"| `{mid}` | " + " | ".join(cells) + " |")

    L.append("\n## Cost — measured, never estimated\n")
    L.append("| Model | Mean ¥/item | p95 ¥/item | Mean image tokens | Total ¥ |")
    L.append("|---|---:|---:|---:|---:|")
    for mid, m in summary.items():
        c, it = m["cost_cny"], m["image_tokens_mean"]
        L.append(
            f"| `{mid}` | "
            f"{c['mean']:.4f} | {c['p95']:.4f} | {it:.0f} | {c['total']:.2f} |"
            if c["mean"] is not None and it is not None
            else f"| `{mid}` | - | - | - | - |"
        )

    L.append("\n## Latency — aggregate\n")
    slo = gates.get("latency_p95_ms_max")
    L.append("Elapsed is encode + request + retry backoff. **The operator waits "
             "for elapsed**, so the SLO is gated on it. Request time is shown "
             "separately to expose how much of the tail is retries.\n")
    L.append(f"| Model | elapsed p50 | p95 | p99 | max | request p95 | SLO ({slo} ms) |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for mid, m in summary.items():
        e, q = m["elapsed_ms"], m["request_ms"]
        flag = "-" if m["slo_violation"] is None else (
            "**VIOLATION**" if m["slo_violation"] else "ok")
        L.append(f"| `{mid}` | {e['p50'] or '-'} | {e['p95'] or '-'} | "
                 f"{e['p99'] or '-'} | {e['max'] or '-'} | {q['p95'] or '-'} | {flag} |")

    for mid, m in summary.items():
        if m["slo_violating_samples"]:
            L.append(f"\n`{mid}` exceeded the SLO on **{len(m['slo_violating_samples'])}** "
                     f"samples: {', '.join('`%s`' % s for s in m['slo_violating_samples'][:20])}"
                     + (" …" if len(m["slo_violating_samples"]) > 20 else ""))

    # Required output: one row per piece. Aggregates say whether the fleet
    # meets the SLO; this table says which pieces are slow, which is what
    # makes a slow path fixable.
    L.append("\n## Latency — per sample\n")
    L.append("| Sample | Model | Elapsed ms | Request ms | Encode ms | Retry wait ms | Retries | Note |")
    L.append("|---|---|---:|---:|---:|---:|---:|---|")
    for r in sorted(rows, key=lambda x: -(x.elapsed_ms or 0)):
        notes = []
        if slo is not None and r.elapsed_ms and r.elapsed_ms > slo:
            notes.append("**SLO**")
        # Flag rows where retries dominate: the request was fine, the wait was not.
        if r.elapsed_ms and r.request_ms and r.elapsed_ms > r.request_ms * 1.2:
            notes.append("retry-dominated")
        if r.error or r.http_error:
            notes.append(f"err:{r.http_error or r.error}")
        L.append(
            f"| `{r.sample_id}` | `{r.model_id}` | {r.elapsed_ms or '-'} | "
            f"{r.request_ms or '-'} | {r.encode_ms or '-'} | "
            f"{r.retry_wait_ms or 0} | {r.retries} | {' '.join(notes) or '-'} |"
        )

    L.append("\n> These timings are client-to-API only. They **exclude** the "
             "4G/5G upload of three 1080p frames from the Pad, which is a "
             "separate and possibly larger term. Do not read the figures above "
             "as end-to-end operator latency.\n")

    L.append("\n## Errors and retries\n")
    L.append("| Model | Errors | Retries | Parse failure rate |")
    L.append("|---|---:|---:|---:|")
    for mid, m in summary.items():
        L.append(f"| `{mid}` | {m['error_count']} | {m['retry_count']} | "
                 f"{pct(m['parse_failure_rate'])} |")

    # The highest-value section. Aggregate verdicts produced no actionable
    # signal across four prior rounds; the specific failures do.
    L.append("\n## Failure gallery\n")
    fails = [r for r in rows if r.parse_ok and r.truth and r.verdict_correct is False]
    if not fails:
        L.append("_No verdict failures recorded._\n")
    for r in sorted(fails, key=lambda x: (x.sample_id, x.model_id)):
        kind = "FALSE ACCEPT" if r.false_accept else ("FALSE REJECT" if r.false_reject else "MISMATCH")
        L.append(f"### `{r.sample_id}` — `{r.model_id}` — **{kind}**\n")
        L.append(f"- truth: `{json.dumps(r.truth, ensure_ascii=False)}`")
        L.append(f"- predicted: `{json.dumps(r.predicted, ensure_ascii=False)}`")
        L.append(f"- flagged for review: `{r.flagged}`\n")

    L.append("\n---\n")
    L.append("_This report states what was measured. It does not recommend a "
             "model, a plan, or a purchase._\n")
    return "\n".join(L)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Offline scorer. Makes no API calls.")
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--ground-truth", required=True, type=Path)
    ap.add_argument("--models", required=True, type=Path)
    ap.add_argument("--gates", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    for p in (args.raw, args.ground_truth, args.models, args.gates):
        if not p.exists():
            raise SystemExit(f"fatal: not found: {p}")

    truth: dict[str, dict] = {}
    for line in args.ground_truth.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            truth[rec["sample_id"]] = rec

    specs = load_models(args.models)
    gates = load_gates(args.gates)

    rows = build_rows(args.raw, truth, specs)
    if not rows:
        raise SystemExit(f"fatal: no raw response files in {args.raw}")

    summary = summarise(rows, gates)
    run_id = args.out.name

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps(
            {"run_id": run_id, "gates": gates, "summary": summary,
             "rows": [asdict(r) for r in rows]},
            indent=2, ensure_ascii=False),
        encoding="utf-8")
    (args.out / "report.md").write_text(
        render_md(summary, rows, gates, run_id), encoding="utf-8")

    n_samples = len({r.sample_id for r in rows})
    print(f"scored {len(rows)} cells over {n_samples} samples, "
          f"{len(summary)} models")
    for mid, m in summary.items():
        print(f"  {mid:<32} {verdict_for(mid, m, gates):<14} "
              f"n={m['n_scored']}")
    if n_samples < MIN_N_FOR_CLAIM:
        print(f"\nWARNING: n={n_samples} < {MIN_N_FOR_CLAIM}. "
              f"All accuracy verdicts are INCONCLUSIVE.", file=sys.stderr)
    print(f"\nwritten: {args.out}/report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
