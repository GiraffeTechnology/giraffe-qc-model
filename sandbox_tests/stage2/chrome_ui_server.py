"""Serve the Stage 2 browser validation surface from recorded sandbox evidence.

This server is intentionally test-only.  It never connects to a camera or an
inference provider, and it binds to loopback by default.
"""
from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = Path(__file__).with_name("chrome_ui.html")
ARM64_PROBE = REPO_ROOT / "sandbox_tests/reports/evidence/stage2/arm64-cv-probe.json"
DRIVE_PROBE = REPO_ROOT / "sandbox_tests/reports/evidence/stage2/drive-probe.json"
FIXTURE_PATH = REPO_ROOT / "tests/fixtures/qc/capture_red_square_pass.png"

STATE_CONTRACTS = {
    "simulator-ready": {
        "heading": "ARM64 simulator ready",
        "status": "READY",
        "tone": "success",
        "detail": "QEMU aarch64 guest verified · external-drive-backed session",
        "fail_closed": False,
        "result_count": 0,
        "show_fixture": False,
    },
    "simulated-capture": {
        "heading": "Simulated capture",
        "status": "FIXTURE LOADED",
        "tone": "info",
        "detail": "Repository fixture loaded · camera is not connected",
        "fail_closed": False,
        "result_count": 0,
        "show_fixture": True,
    },
    "cv-success": {
        "heading": "Standalone CV evidence",
        "status": "CV COMPLETE",
        "tone": "success",
        "detail": "Normalized image and informational CV evidence are available; no autonomous final verdict",
        "fail_closed": False,
        "result_count": 1,
        "show_fixture": True,
    },
    "cv-anomaly": {
        "heading": "Insufficient CV evidence",
        "status": "REVIEW REQUIRED",
        "tone": "warning",
        "detail": "Invalid or incomplete evidence is blocked; silent pass is forbidden",
        "fail_closed": True,
        "result_count": 0,
        "show_fixture": True,
    },
    "simulator-unavailable": {
        "heading": "Simulator unavailable",
        "status": "BLOCKED",
        "tone": "error",
        "detail": "SIMULATOR_UNAVAILABLE · mount/dependency readiness failed",
        "fail_closed": True,
        "result_count": 0,
        "show_fixture": False,
    },
    "refresh-retry": {
        "heading": "Simulator recovered",
        "status": "RETRY COMPLETE",
        "tone": "success",
        "detail": "Dependency restored · exactly one result retained · no duplicate result",
        "fail_closed": False,
        "result_count": 1,
        "show_fixture": False,
    },
}

STATE_TRANSLATIONS = {
    "simulator-ready": {
        "zh-CN": {
            "heading": "ARM64 模拟器已就绪",
            "status": "已就绪",
            "detail": "QEMU aarch64 客体已验证 · 会话数据由外置硬盘承载",
        },
    },
    "simulated-capture": {
        "zh-CN": {
            "heading": "模拟采集",
            "status": "测试图片已载入",
            "detail": "已载入仓库测试图片 · 未连接摄像头",
        },
    },
    "cv-success": {
        "zh-CN": {
            "heading": "独立 CV 证据",
            "status": "CV 已完成",
            "detail": "标准化图片及信息性 CV 证据已生成；不会自动形成最终判定",
        },
    },
    "cv-anomaly": {
        "zh-CN": {
            "heading": "CV 证据不足",
            "status": "需要复核",
            "detail": "无效或不完整证据会被阻断；禁止静默放行",
        },
    },
    "simulator-unavailable": {
        "zh-CN": {
            "heading": "模拟器不可用",
            "status": "已阻断",
            "detail": "SIMULATOR_UNAVAILABLE · 挂载或依赖就绪检查失败",
        },
    },
    "refresh-retry": {
        "zh-CN": {
            "heading": "模拟器已恢复",
            "status": "重试完成",
            "detail": "依赖已恢复 · 仅保留一条结果 · 未产生重复结果",
        },
    },
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_state(case_id: str) -> dict:
    if case_id not in STATE_CONTRACTS:
        raise KeyError(case_id)
    arm64 = _read_json(ARM64_PROBE)
    drive = _read_json(DRIVE_PROBE)
    first_case = arm64["cases"][0]
    cv_result = first_case["cv_result"]
    drive_ready = all(
        bool(drive.get(key))
        for key in ("write_fsync_completed", "read_back_completed", "sha256_matches")
    )
    contract = STATE_CONTRACTS[case_id]
    return {
        "case_id": case_id,
        **contract,
        "translations": {
            "en": {
                "heading": contract["heading"],
                "status": contract["status"],
                "detail": contract["detail"],
            },
            **STATE_TRANSLATIONS[case_id],
        },
        "mock_label": "NON-PRODUCTION MOCK",
        "method": "QEMU aarch64",
        "machine": arm64["runtime"]["machine"],
        "external_volume": drive["volume_name"],
        "external_drive_ready": drive_ready,
        "fixture_ref": first_case["input_ref"],
        "fixture_url": "/fixture.png",
        "normalized_size": f"{cv_result['input_width_px']} × {cv_result['input_height_px']}",
        "verdict_effect": cv_result["verdict_effect"],
        "camera_connected": False,
        "inference_call_count": 0,
    }


class Stage2ChromeHandler(BaseHTTPRequestHandler):
    server_version = "GiraffeStage2Chrome/1.0"

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/stage2"}:
            self._send(HTTPStatus.OK, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/fixture.png":
            self._send(HTTPStatus.OK, FIXTURE_PATH.read_bytes(), "image/png")
            return
        if parsed.path == "/api/state":
            case_id = parse_qs(parsed.query).get("id", ["simulator-ready"])[0]
            try:
                state = build_state(case_id)
            except KeyError:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    json.dumps({"error": "unknown_state", "case_id": case_id}).encode(),
                    "application/json",
                )
                return
            self._send(
                HTTPStatus.OK,
                json.dumps(state, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Stage2ChromeHandler)
    print(f"Stage 2 Chrome UI available at http://{args.host}:{args.port}/stage2", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
