"""Device health metrics collection (mock-friendly, §8.2)."""
from __future__ import annotations


def collect_metrics(mock: bool = True, active_job_count: int = 0) -> dict:
    """Return a device metrics dict.

    In mock mode returns deterministic, healthy values so CI is stable. A real
    Jetson build would read tegrastats / psutil here.
    """
    if mock:
        return {
            "cpu_usage_percent": 21.5,
            "gpu_usage_percent": 0.0,
            "memory_used_mb": 880.0,
            "memory_total_mb": 2048.0,
            "temperature_celsius": 48.2,
            "disk_used_percent": 33.1,
            "power_mode": "MAXN",
        }
    try:  # pragma: no cover - real-hardware path, not exercised in CI
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return {
            "cpu_usage_percent": psutil.cpu_percent(interval=None),
            "gpu_usage_percent": 0.0,
            "memory_used_mb": (vm.total - vm.available) / 1e6,
            "memory_total_mb": vm.total / 1e6,
            "temperature_celsius": None,
            "disk_used_percent": psutil.disk_usage("/").percent,
        }
    except Exception:
        return {"cpu_usage_percent": 0.0, "memory_used_mb": 0.0, "memory_total_mb": 2048.0}
