.PHONY: sync sync-dev test test5 test-qwen test-multimodal clean-test

sync:
	uv sync

sync-dev:
	uv sync --group dev

test:
	uv run pytest tests/ -v

test5:
	for i in 1 2 3 4 5; do \
		echo "===== TEST RUN $$i / 5 ====="; \
		uv run pytest tests/ -v || exit 1; \
	done

# Live multimodal / Qwen-DashScope integration tests.
# Requires QWEN_API_KEY or DASHSCOPE_API_KEY in the environment.
# Never hardcode keys in this file, tests, docs, or GitHub Actions YAML.
test-multimodal:
	@if [ -z "$$QWEN_API_KEY" ] && [ -z "$$DASHSCOPE_API_KEY" ]; then \
		echo "ERROR: QWEN_API_KEY or DASHSCOPE_API_KEY is required for live multimodal integration tests."; \
		exit 1; \
	fi
	RUN_QWEN_INTEGRATION=1 \
	QC_ENGINE_MODE=cloud_qwen_dev \
	LLM_ENABLE_REAL_CALLS=true \
	QWEN_CLOUD_ENABLED=true \
	ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true \
	uv run pytest tests/integration/ -v

# Backward-compatible alias for older Qwen-specific docs / scripts.
test-qwen: test-multimodal

clean-test:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
