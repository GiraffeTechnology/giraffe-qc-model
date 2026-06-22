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

test-qwen:
	RUN_QWEN_INTEGRATION=1 \
	QC_ENGINE_MODE=cloud_qwen_dev \
	LLM_ENABLE_REAL_CALLS=true \
	QWEN_CLOUD_ENABLED=true \
	ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true \
	uv run pytest tests/integration/ -v

test-multimodal:
	RUN_MULTIMODAL_INTEGRATION=1 \
	MULTIMODAL_ENABLE_REAL_CALLS=true \
	MULTIMODAL_PROVIDER=qwen \
	QC_ALLOW_CLOUD_FALLBACK=true \
	QC_ALLOW_SEND_IMAGES_TO_CLOUD=true \
	uv run pytest tests/integration/ -v

clean-test:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
