# MNN Android Native Libraries

This directory must contain the MNN pre-built shared libraries for `arm64-v8a`
before the APK can be built or run.

## Required files

| File | Required | Source |
|------|----------|--------|
| `libMNN.so` | **Yes** | MNN core inference runtime |
| `libMNN_Express.so` | **Yes** | MNN Express API layer |
| `libllm.so` | **Yes** | MNN LLM engine — `MNN_SEP_BUILD=ON` (MNN default) compiles the LLM engine as a separate shared library, not merged into `libMNN.so` |
| `libMNN_CL.so` | Optional | OpenCL backend (improves GPU performance if available) |

These files are **not committed** to git (large binaries). Populate them by running:

```bash
bash scripts/download_mnn_android_libs.sh
```

Or build MNN from source for Android arm64-v8a with `-DMNN_BUILD_LLM=ON`
and copy the output `.so` files here.

Gradle automatically packages all `.so` files in this directory into the APK.
The CMakeLists.txt imports them for linking via `IMPORTED` libraries.

## MNN headers

The C++ bridge (`native_mnn_qwen_bridge.cpp`) requires MNN headers at:
```
apps/android-qc/mnn_android/include/llm/llm.hpp
apps/android-qc/mnn_android/include/MNN/Interpreter.hpp
```

The download script populates both the `.so` files here and the headers above.

See `docs/PAD_LOCAL_MNN_DEPLOYMENT.md` for full deployment instructions.
