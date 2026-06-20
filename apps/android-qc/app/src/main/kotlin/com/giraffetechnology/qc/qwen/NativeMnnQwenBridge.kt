package com.giraffetechnology.qc.qwen

/**
 * JNI bridge to the native MNN inference runtime.
 *
 * Library load order (must be explicit — Android linker does not auto-load transitive deps):
 *   1. libMNN.so              — core MNN inference runtime
 *   2. libMNN_Express.so      — MNN Express API layer
 *   3. libllm.so              — MNN LLM engine (MNN_SEP_BUILD=ON produces a separate .so)
 *   4. libgiraffe_mnn_qwen_bridge.so — this project JNI wrapper (links against libllm.so)
 *
 * Pre-built MNN .so files must be in:
 *   apps/android-qc/app/src/main/jniLibs/arm64-v8a/
 * MNN headers must be in:
 *   apps/android-qc/mnn_android/include/
 * Run scripts/download_mnn_android_libs.sh to fetch both.
 *
 * If any loadLibrary call throws, isAvailable() propagates the error;
 * MnnRuntimeLoader.loadNativeLibs() catches it and returns false,
 * causing all inspections to return review_required.
 */
object NativeMnnQwenBridge {

    init {
        System.loadLibrary("MNN")
        System.loadLibrary("MNN_Express")
        System.loadLibrary("llm")
        System.loadLibrary("giraffe_mnn_qwen_bridge")
    }

    /** Returns true if the bridge initialised successfully (all libs loaded). */
    fun isAvailable(): Boolean = true

    /**
     * Load Qwen3-VL model from [modelDir] (must contain llm_config.json + all 10 model files).
     * @return Opaque non-zero handle on success; 0 on any failure.
     */
    external fun nativeLoadModel(modelDir: String): Long

    /**
     * Run one VL inference pass.
     *
     * @param handle              Non-zero handle from [nativeLoadModel].
     * @param imageInputJson      JSON: {"standard_photos":["/path/..."],"captured_photo":"/path/..."}
     * @param prompt              Full QC prompt (enable_thinking=false directive included).
     * @param inferenceParamsJson JSON: {"max_new_tokens":1024,"temperature":0.1,"do_sample":false}
     * @return Raw text from model, or error JSON with inspection_result=review_required.
     */
    external fun nativeRunInference(
        handle: Long,
        imageInputJson: String,
        prompt: String,
        inferenceParamsJson: String,
    ): String

    /**
     * Release the model and free all native memory.
     * Must be called when the runtime loader is destroyed.
     */
    external fun nativeUnloadModel(handle: Long)
}
