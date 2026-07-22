# Stage 3 Group B — remote adapter and secure tunnel

Group B (`docs/STAGE3_AB_TESTING_SPEC.md` §2) screens with Jetson-local CV
plus a VLM served remotely. This document covers the two pieces GAP-06 and
GAP-07 required: the repo-side adapter that speaks the remote host's actual
`/v1/chat/completions` contract, and the restricted tunnel that carries that
traffic. It also states the one prerequisite this repository cannot deliver
(GAP-08): a `/model-info` endpoint on the remote host itself.

## 1. Repo-side adapter (GAP-06 — delivered in this repo)

`src/qc_model/production/remote_chat_provider.py` implements
`RemoteChatVlmInspectionProvider`, selected via
`QC_PRODUCTION_INSPECTION_PROVIDER=remote_chat_vlm` (or the Stage-3-explicit
alias `stage3_group_b`). Unlike `ServerVLMInspectionProvider` (which POSTs to
`{base_url}/v1/inspect` and expects the repo's own inspection JSON shape
directly), this adapter:

- builds a strict prompt embedding the same required response schema
  (`detection_point_code`, `disposition`, `observed_features`, …) and posts
  an OpenAI-compatible vision chat request to `{VLM_BASE_URL}/v1/chat/completions`;
- extracts `choices[0].message.content`, strips any Markdown code fence,
  parses the first complete JSON object, and rejects anything else;
- validates the parsed object with the same `parse_provider_response` used by
  the `/v1/inspect` path, so both wire protocols land on one audited schema;
- only embeds a **local file path** or an already-encoded `data:` URL as the
  image; `http(s)` references are refused (no general-purpose outbound
  fetcher exists behind the tunnel, so accepting arbitrary URLs would be an
  unnecessary SSRF surface);
- enforces `VLM_MAX_IMAGE_BYTES` (default 5 MiB) before embedding an image;
- never falls back to mock, another provider, or a guessed result on any
  transport, timeout, or schema failure — it raises
  `ProductionProviderNotConfigured` / `ProductionProviderError` /
  `ProductionProviderSchemaError`.

### Configuration

```bash
QC_PRODUCTION_INSPECTION_PROVIDER=remote_chat_vlm   # or: stage3_group_b
VLM_BASE_URL=http://127.0.0.1:<restricted-tunnel-port>   # loopback only — see §2
VLM_MODEL=<remote model alias, e.g. qwen3-vl-4b-int4>
VLM_API_KEY=<optional bearer token, if the tunnel endpoint requires one>
VLM_TIMEOUT_SECONDS=30
VLM_MAX_IMAGE_BYTES=5242880
```

`VLM_BASE_URL` must always resolve to a loopback address on the Jetson —
never the remote host's real address directly. The tunnel in §2 is what maps
that loopback port to the remote service.

## 2. Restricted tunnel (GAP-07)

The remote chat endpoint must never be exposed to a public interface, and the
Jetson must never hold a credential broader than "forward this one port."

### 2.1 SSH key restrictions

Provision a dedicated key pair for the Jetson → remote-host tunnel. On the
remote host's `authorized_keys` entry for that key, force these restrictions
(adjust the remote loopback port to the actual deployed value):

```text
command="/bin/false",no-agent-forwarding,no-X11-forwarding,no-pty,permitopen="127.0.0.1:<remote-service-port>" ssh-ed25519 AAAA... jetson-stage3-group-b-tunnel
```

- `command="/bin/false"` — the key can never open an interactive shell.
- `no-agent-forwarding`, `no-X11-forwarding`, `no-pty` — no lateral movement
  surface.
- `permitopen="127.0.0.1:<remote-service-port>"` — the key may forward
  *only* to the remote service's own loopback port, nothing else on the
  remote host's network.

### 2.2 systemd-managed tunnel with auto-reconnect

Install `deploy/jetson/giraffe-stage3-group-b-tunnel.service` (template in
this repo). It runs `autossh` (or a `ssh -N` + `Restart=always` fallback if
`autossh` is unavailable) forwarding a local Jetson loopback port to the
remote service's loopback port, and never widens the bind beyond `127.0.0.1`
on the Jetson side either.

### 2.3 Health must distinguish three states

A Stage 3 Group B report's `network` block (see the schema in
`docs/STAGE3_AB_TESTING_SPEC.md` §4) must be able to tell these apart, not
collapse them into one boolean:

1. **Jetson CV ready** — the local CV pipeline is healthy (independent of the
   tunnel).
2. **Tunnel ready** — the SSH tunnel process is up and the forwarded local
   port accepts TCP connections.
3. **Remote model ready** — the remote service itself reports a loaded model
   through the forwarded port (this is where GAP-08, below, applies).

### 2.4 Fail-closed on remote unavailability

If the remote host is unreachable, the tunnel is down, or the remote model
is not ready, `RemoteChatVlmInspectionProvider.inspect()` raises
`ProductionProviderError` from the transport-exception branch. The caller
must **not** catch this and fall back to Group A, mock, or any other
provider — a Group B failure is a Group B failure, recorded as such.

## 3. Remote-side prerequisite this repo cannot deliver (GAP-08)

The remote host's chat-completions service is not part of this repository —
it is a separately deployed and separately maintained MNN serving process.
This repo can only be the *client* of that service; it cannot add an
endpoint to it.

**Before a Group B report may claim a specific INT4 revision/quantization
identity for the remote model**, the remote service needs one of:

- an extended `/health` response that includes a non-sensitive, auditable
  model manifest summary (name, revision, quantization, weight digest), or
- a dedicated `/model-info` endpoint returning the same.

Until that exists, `RemoteChatVlmInspectionProvider` has no way to verify the
remote model's claimed identity beyond the `model` field the response itself
echoes back — which is not independent evidence. A Group B report's
`model.manifest_sha256` field cannot be honestly populated until the remote
side ships this. Track this as an external dependency, not a gap in this
repository's code.

The remote service's current backend is CPU (report it as `backend: "cpu"`
in the Stage 3 report — never as GPU-accelerated unless independently
measured).
