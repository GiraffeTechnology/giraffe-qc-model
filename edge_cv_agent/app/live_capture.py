"""Device-local live auto-lock capture (Live-Capture Auto-Lock addendum §2).

The lock/capture state machine runs *on the device*; only the final still frame
+ metadata crosses the API boundary (§5.2/§5.3). This is a pure, dependency-free
implementation of the debounce + dedup logic so it is unit-testable without a
camera:

    watching -> candidate_detected -> locking -> locked -> captured -> uploading
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

WATCHING = "watching"
CANDIDATE_DETECTED = "candidate_detected"
LOCKING = "locking"
LOCKED = "locked"
CAPTURED = "captured"
UPLOADING = "uploading"


@dataclass
class LiveCaptureTracker:
    """Debounce + cooldown tracker for one camera feed.

    ``confidence_threshold``: minimum per-frame confidence to count as a hit.
    ``debounce_frames``: consecutive hits on the *same* object id required to
    lock (prevents capturing on a single noisy frame).
    ``recapture_cooldown_seconds``: after a capture, suppress the same tracked
    object for this long (dedup — avoids flooding the same physical item).
    """

    confidence_threshold: float = 0.6
    debounce_frames: int = 3
    recapture_cooldown_seconds: float = 5.0
    _now = staticmethod(time.monotonic)

    state: str = WATCHING
    _current_object: Optional[str] = None
    _streak: int = 0
    _last_capture_at: dict = field(default_factory=dict)  # object_id -> monotonic ts

    def observe(self, object_id: Optional[str], confidence: float) -> Optional[str]:
        """Feed one frame's best candidate. Returns object_id when a capture
        should be triggered *this frame*, else ``None`` and advances state.
        """
        now = self._now()
        if object_id is None or confidence < self.confidence_threshold:
            self.state = WATCHING
            self._current_object = None
            self._streak = 0
            return None

        # Dedup: suppress re-capture within the cooldown window.
        last = self._last_capture_at.get(object_id)
        if last is not None and (now - last) < self.recapture_cooldown_seconds:
            self.state = WATCHING
            return None

        if object_id != self._current_object:
            self._current_object = object_id
            self._streak = 1
            self.state = CANDIDATE_DETECTED
            return None

        self._streak += 1
        if self._streak < self.debounce_frames:
            self.state = LOCKING
            return None

        # Stable across the debounce window → lock + capture.
        self.state = CAPTURED
        self._last_capture_at[object_id] = now
        self._streak = 0
        self._current_object = None
        return object_id
