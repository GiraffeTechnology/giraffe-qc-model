# Giraffe QC Model

AI-native quality control inference system for industrial procurement, with two coordinated deployment targets: an on-device Android Tablet app and a server-side QC model. Both share a strict no-fake-result policy and a common set of field/result conventions, so outputs from both ends remain comparable and auditable.

## Overview

|Target            |Model                   |Inference                                                |Network                       |
|------------------|------------------------|---------------------------------------------------------|------------------------------|
|Android Tablet App|Qwen3-VL-2B-Instruct-MNN|Local, via MNN runtime                                   |Fully offline                 |
|QC Model (Server) |Qwen3-VL-8B             |Local inference, with API fallback on capability overflow|Local-first, network on demand|

## Status

### Android Tablet App

✅ **Working end-to-end** — verified running on real Android Tablet hardware with actual MNN inference calls.

- Ships with a quantized **Qwen3-VL-2B-Instruct-MNN** model bundled into the app.
- Runs **fully offline**: no cloud dependency for SKU matching or QC inference.
- Branch: `android-pad-app`
- Task spec: `CLAUDE_ANDROID_PAD_ITER4A_TASK.md`

### QC Model (Server)

Configured with **Qwen3-VL-8B** as the primary inference model.

- Runs locally by default.
- When local model confidence/capability is insufficient ("capability overflow") for a given case, the server falls back to a cloud API call to supplement the result.
- Cloud calls are a fallback path only — not the default inference route.

## Core Principles

- **No fake results.** The system never fabricates a pass/fail outcome.
- **No silent cloud fallback.** Cloud inference is only invoked on local capability overflow, and is never the default path.
- **No silent degradation.** If the Tablet app's MNN runtime is unavailable, the result must be explicitly marked `MNN pending` / `review_required` rather than defaulting to any pass/fail value.

## Repository Structure

- `android-pad-app/` — Android Tablet client (Kotlin/Java), MNN runtime integration, live camera preview + auto-capture state machine, post-login Task Selection screen with MNN-based SKU matching.
- Server-side QC model components (training/serving/config) — see corresponding subdirectories for setup details.
