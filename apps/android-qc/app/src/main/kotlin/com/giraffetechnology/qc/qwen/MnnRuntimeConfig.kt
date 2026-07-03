package com.giraffetechnology.qc.qwen

/**
 * Configuration for the on-device MNN runtime.
 *
 * The model root is configurable (Work Item 1: "path must be configurable") and
 * defaults to the sideloaded/factory-preloaded location on the Pad. All file
 * names below are relative to [modelRoot].
 *
 * A model directory is only considered loadable when ALL of the following exist
 * under [modelRoot]:
 *   - every entry in [requiredWeightFiles] (both the LLM and the visual encoder),
 *   - [tokenizerFile],
 *   - [checksumFile] (used for fail-closed integrity verification).
 *
 * @property modelRoot Absolute path to the model directory. Default: the Pad's
 *   sideload location. Override via [MnnRuntimeLoader.loadModel] for benchmarks
 *   or alternate provisioning.
 * @property requiredWeightFiles Weight files that must all be present AND load
 *   into a non-zero native handle before the runtime may report Ready. Both the
 *   LLM and the visual encoder are mandatory for a vision-language pass.
 * @property tokenizerFile Tokenizer vocabulary required by the LLM runtime.
 * @property checksumFile `sha256sum`-format manifest ("<hex>␠␠<filename>" per
 *   line). Presence is mandatory; when [verifyChecksumOnLoad] is true every
 *   listed file is hashed and compared, and any mismatch fails closed.
 * @property configFile MNN LLM config consumed by the native loader. If absent
 *   at [modelRoot] the native bridge synthesizes a minimal config from the
 *   weight files (see cpp/mnn_qwen_jni.cpp).
 * @property verifyChecksumOnLoad When true, cold start hashes every file listed
 *   in [checksumFile]. This reads the full model (~1.3 GB) and adds seconds to
 *   load time; it is the integrity gate that turns a corrupt/partial model into
 *   NotReady instead of a silent bad inference.
 */
data class MnnRuntimeConfig(
    val modelRoot: String = DEFAULT_MODEL_ROOT,
    val requiredWeightFiles: List<String> = listOf("llm.mnn.weight", "visual.mnn.weight"),
    val tokenizerFile: String = "tokenizer.txt",
    val checksumFile: String = "checksum.sha256",
    val configFile: String = "config.json",
    val verifyChecksumOnLoad: Boolean = true,
) {
    companion object {
        /** Default on-device model location for the padLocal edition. */
        const val DEFAULT_MODEL_ROOT = "/sdcard/qwen_2b_mnn"
    }
}
