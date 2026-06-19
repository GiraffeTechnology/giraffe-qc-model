"""WebSocket endpoint for Pad real-time QC result feed.

Pad connects to  ws://<host>:<port>/ws/pad?tenant_id=<t>&sku_id=<s>

Protocol
--------
Backend → Pad:
  {"type": "inspection_result", "sku_id": "...", "passed": true,
   "confidence": 0.95, "summary": "..."}
  {"type": "no_result", "sku_id": "..."}

Pad → Backend:
  {"type": "refresh"}  — request immediate push of latest result
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Generator, Optional, Tuple

from fastapi import APIRouter
from fastapi import WebSocket, WebSocketDisconnect

from src.db.qc_models import InspectionRun
from src.db.session import _get_session_local

ws_router = APIRouter()

_POLL_INTERVAL_SEC = 3.0


@contextmanager
def _db_session() -> Generator:
    """Short-lived DB session scoped to a single query."""
    session = _get_session_local()()
    try:
        yield session
    finally:
        session.close()


def _latest_payload(sku_id: str, tenant_id: str) -> Tuple[dict, Optional[str]]:
    """Return (ws_message, inspection_id) for the latest completed run."""
    with _db_session() as db:
        run = (
            db.query(InspectionRun)
            .filter(
                InspectionRun.sku_id == sku_id,
                InspectionRun.tenant_id == tenant_id,
                InspectionRun.status == "done",
            )
            .order_by(InspectionRun.completed_at.desc())
            .first()
        )
    if run is None:
        return {"type": "no_result", "sku_id": sku_id}, None
    return {
        "type": "inspection_result",
        "sku_id": run.sku_id,
        "inspection_id": run.id,
        "passed": run.overall_result == "pass",
        "confidence": run.confidence,
        "summary": run.summary,
    }, run.id


@ws_router.websocket("/ws/pad")
async def pad_websocket(
    websocket: WebSocket,
    tenant_id: str = "default",
    sku_id: str = "default",
) -> None:
    await websocket.accept()
    last_id: Optional[str] = None
    try:
        # Push current latest result immediately on connect.
        payload, last_id = _latest_payload(sku_id, tenant_id)
        await websocket.send_text(json.dumps(payload))

        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_POLL_INTERVAL_SEC
                )
                msg = json.loads(raw)
                if msg.get("type") == "refresh":
                    payload, last_id = _latest_payload(sku_id, tenant_id)
                    await websocket.send_text(json.dumps(payload))
            except asyncio.TimeoutError:
                # Poll for new results; only push if something changed.
                payload, new_id = _latest_payload(sku_id, tenant_id)
                if new_id and new_id != last_id:
                    last_id = new_id
                    await websocket.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
