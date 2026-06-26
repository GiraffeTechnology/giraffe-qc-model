.PHONY: test test-parser test-cloud test-device test-all fixtures check-secrets

# Default: offline unit + integration tests only (CI-safe, excludes real_api and device)
test:
	python -m pytest tests/ -v -m "not real_api and not device"

# QcResultParser unit tests specifically
test-parser:
	python -m pytest tests/test_parser.py -v --tb=short

# B1 cloud real API tests (requires DASHSCOPE_API_KEY)
test-cloud:
	@test -n "$$DASHSCOPE_API_KEY" || (echo "ERROR: DASHSCOPE_API_KEY not set" && exit 1)
	python -m pytest tests/test_cloud_b1.py -v -m real_api -s

# B2 device tests (requires physical device; set DEVICE_ADDR)
test-device:
	python -m pytest tests/ -v -m device -s

# Full suite including real API and device
test-all:
	python -m pytest tests/ -v

# Generate synthetic PNG test fixtures
fixtures:
	python scripts/generate_test_fixtures.py

# Scan staged files for leaked secrets before commit
check-secrets:
	@echo "Scanning staged changes for sk- patterns..."
	@! git diff --cached | grep -E 'sk-[A-Za-z0-9._-]{10}' \
		&& echo "OK: no secrets in staged changes"
	@echo "Scanning tests/ for sk- patterns..."
	@! grep -r 'sk-' tests/ --include='*.py' --include='*.json' 2>/dev/null \
		&& echo "OK: no secrets in tests/"
