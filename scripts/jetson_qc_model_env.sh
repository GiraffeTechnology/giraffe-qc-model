#!/usr/bin/env bash
# Jetson test-machine deployment environment for giraffe-qc-model.
#
# TEST ONLY, NOT PRODUCTION:
# - One Jetson may simulate both Pad and Server roles.
# - Simulated still photos may replace CV module input.
# - SQLite, APP_ENV=test, Edge CV mock/fallback, and insecure registration are
#   allowed only for this hardware/configuration test profile.
# - Do not reuse this file for real factory production.

export APP_ENV=test
export SESSION_SECRET=jetson-qc-model-test-session-secret

export QC_DB_URL=sqlite:////home/giraffe/work/giraffe-qc-model/data/jetson/giraffe_qc.db
export SAMPLE_STORE_DIR=/home/giraffe/work/giraffe-qc-model/data/jetson/samples
export CAPTURE_DIR=/home/giraffe/work/giraffe-qc-model/data/jetson/captures

export QC_ENGINE_MODE=on_device_first
export QC_RUNTIME_EDITION=padLocal
export QC_VISION_RUNTIME_ENV=tablet_mnn

export LLM_ENABLE_REAL_CALLS=false
export QWEN_CLOUD_ENABLED=false
export ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=false

export QWEN_MNN_MODEL_NAME=Qwen3-VL-2B-Instruct-MNN
export QWEN_MNN_MODEL_DIR=/home/giraffe/work/qwen3-vl-2b-mnn
export QWEN_VISION_MODEL=Qwen3-VL-2B-Instruct-MNN

export EDGE_CV_ENABLED=true
export EDGE_CV_HOTPLUG_ENABLED=true
export EDGE_CV_MOCK_ENABLED=true
export EDGE_CV_CPU_FALLBACK=true
export EDGE_CV_ALLOW_INSECURE_REGISTRATION=true
export EDGE_CV_MODEL_DIR=/home/giraffe/work/qwen3-vl-2b-mnn
export EDGE_CV_OUTPUT_DIR=/home/giraffe/work/giraffe-qc-model/artifacts/edge_cv_outputs
