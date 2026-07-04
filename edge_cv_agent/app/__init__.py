"""Lightweight Edge CV agent (Jetson Nano 2GB / mock runner).

Pull-based: register → heartbeat → pull job → run CV → upload result. Runs in
mock mode with no GPU/Jetson so CI never needs real hardware
(``EDGE_AGENT_MOCK_MODE=true``). See edge_cv_agent/README.md.
"""
