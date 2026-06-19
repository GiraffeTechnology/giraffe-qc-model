/**
 * native_mnn_qwen_bridge.cpp
 *
 * JNI bridge: Kotlin NativeMnnQwenBridge <-> MNN LLM C++ runtime.
 *
 * Build requirements:
 *   - MNN Android pre-built libs + headers (see scripts/download_mnn_android_libs.sh)
 *   - C++17
 *   - NDK r25c+ for arm64-v8a
 *
 * MNN LLM API used:
 *   MNN::Transformer::Llm::createLLM(configPath, modelDir) -> Llm*
 *   llm->load()
 *   llm->response_nohistory(fullPrompt)  -> std::string
 *   llm->reset()
 *   delete llm
 *
 * All exceptions are caught and returned as JSON with inspection_result=review_required.
 * No hardcoded outputs. No cloud calls. No fallback paths.
 */

#include <jni.h>
#include <android/log.h>
#include <string>
#include <vector>
#include <stdexcept>

// MNN-LLM header.
// Installed by scripts/download_mnn_android_libs.sh into apps/android-qc/mnn_android/include/
// If the header ships at a different path in your MNN version, adjust CMakeLists.txt include dirs.
#include "llm/llm.hpp"

#define LOG_TAG "GiraffeQC_MNN"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN,  LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// ---------------------------------------------------------------------------
// JNI string helpers
// ---------------------------------------------------------------------------

static std::string jstr_to_str(JNIEnv* env, jstring js) {
    if (!js) return "";
    const char* c = env->GetStringUTFChars(js, nullptr);
    std::string s(c);
    env->ReleaseStringUTFChars(js, c);
    return s;
}

static jstring str_to_jstr(JNIEnv* env, const std::string& s) {
    return env->NewStringUTF(s.c_str());
}

// ---------------------------------------------------------------------------
// Naive JSON field extraction (avoids requiring a JSON library in C++)
// ---------------------------------------------------------------------------

static std::string json_string_field(const std::string& json, const std::string& key) {
    std::string needle = "\"" + key + "\"";
    size_t k = json.find(needle);
    if (k == std::string::npos) return "";
    size_t colon = json.find(':', k + needle.size());
    if (colon == std::string::npos) return "";
    size_t s = json.find('"', colon + 1);
    if (s == std::string::npos) return "";
    size_t e = json.find('"', s + 1);
    if (e == std::string::npos) return "";
    return json.substr(s + 1, e - s - 1);
}

static std::vector<std::string> json_string_array(const std::string& json, const std::string& key) {
    std::vector<std::string> out;
    std::string needle = "\"" + key + "\"";
    size_t k = json.find(needle);
    if (k == std::string::npos) return out;
    size_t arr = json.find('[', k);
    if (arr == std::string::npos) return out;
    size_t end = json.find(']', arr);
    if (end == std::string::npos) return out;
    std::string body = json.substr(arr + 1, end - arr - 1);
    size_t p = 0;
    while (true) {
        size_t s = body.find('"', p);
        if (s == std::string::npos) break;
        size_t e = body.find('"', s + 1);
        if (e == std::string::npos) break;
        out.push_back(body.substr(s + 1, e - s - 1));
        p = e + 1;
    }
    return out;
}

// ---------------------------------------------------------------------------
// Qwen3-VL chat prompt with image tokens.
// MNN-LLM processes <img>path</img> during tokenisation.
// ---------------------------------------------------------------------------

static std::string build_vlm_prompt(
    const std::vector<std::string>& standard_photos,
    const std::string& captured_photo,
    const std::string& text_prompt)
{
    std::string p;
    p += "<|im_start|>user\n";
    for (const auto& path : standard_photos) {
        if (!path.empty()) p += "<img>" + path + "</img>\n";
    }
    if (!captured_photo.empty()) p += "<img>" + captured_photo + "</img>\n";
    p += text_prompt;
    p += "<|im_end|>\n<|im_start|>assistant\n";
    return p;
}

// ---------------------------------------------------------------------------
// Opaque handle wrapping MNN Llm*
// ---------------------------------------------------------------------------

struct LlmHandle {
    MNN::Transformer::Llm* llm;
    std::string            modelDir;
};

// ---------------------------------------------------------------------------
// nativeLoadModel
// ---------------------------------------------------------------------------

extern "C"
JNIEXPORT jlong JNICALL
Java_com_giraffetechnology_qc_qwen_NativeMnnQwenBridge_nativeLoadModel(
    JNIEnv* env, jobject /* thiz */, jstring model_dir_jstr)
{
    std::string modelDir = jstr_to_str(env, model_dir_jstr);
    LOGI("nativeLoadModel start: %s", modelDir.c_str());

    try {
        std::string configPath = modelDir + "/llm_config.json";
        MNN::Transformer::Llm* llm =
            MNN::Transformer::Llm::createLLM(configPath, modelDir);
        if (!llm) {
            LOGE("nativeLoadModel: createLLM returned null (config=%s)", configPath.c_str());
            return 0L;
        }
        llm->load();
        auto* h = new LlmHandle{llm, modelDir};
        jlong ptr = static_cast<jlong>(reinterpret_cast<uintptr_t>(h));
        LOGI("nativeLoadModel success: modelPtr=%lld", (long long)ptr);
        return ptr;
    } catch (const std::exception& e) {
        LOGE("nativeLoadModel exception: %s", e.what());
        return 0L;
    } catch (...) {
        LOGE("nativeLoadModel: unknown C++ exception");
        return 0L;
    }
}

// ---------------------------------------------------------------------------
// nativeRunInference
// ---------------------------------------------------------------------------

extern "C"
JNIEXPORT jstring JNICALL
Java_com_giraffetechnology_qc_qwen_NativeMnnQwenBridge_nativeRunInference(
    JNIEnv* env, jobject /* thiz */,
    jlong   handle_jlong,
    jstring image_input_json_jstr,
    jstring prompt_jstr,
    jstring /* inference_params_json_jstr */)
{
    auto* h = reinterpret_cast<LlmHandle*>(
        static_cast<uintptr_t>(handle_jlong));
    if (!h || !h->llm) {
        LOGE("nativeRunInference: invalid handle");
        return str_to_jstr(env,
            "{\"error\":\"invalid_handle\","
             "\"inspection_result\":\"review_required\"}");
    }

    std::string imgJson    = jstr_to_str(env, image_input_json_jstr);
    std::string textPrompt = jstr_to_str(env, prompt_jstr);
    LOGI("nativeRunInference start: prompt_len=%zu", textPrompt.size());

    try {
        std::vector<std::string> stdPhotos =
            json_string_array(imgJson, "standard_photos");
        std::string capturedPhoto =
            json_string_field(imgJson, "captured_photo");

        std::string fullPrompt = build_vlm_prompt(stdPhotos, capturedPhoto, textPrompt);

        h->llm->reset();
        std::string output = h->llm->response_nohistory(fullPrompt);

        LOGI("nativeRunInference complete: output_len=%zu", output.size());
        return str_to_jstr(env, output);
    } catch (const std::exception& e) {
        LOGE("nativeRunInference exception: %s", e.what());
        std::string err = std::string("{\"error\":\"") + e.what() +
            "\",\"inspection_result\":\"review_required\"}");
        return str_to_jstr(env, err);
    } catch (...) {
        LOGE("nativeRunInference: unknown C++ exception");
        return str_to_jstr(env,
            "{\"error\":\"unknown_native_exception\","
             "\"inspection_result\":\"review_required\"}");
    }
}

// ---------------------------------------------------------------------------
// nativeUnloadModel
// ---------------------------------------------------------------------------

extern "C"
JNIEXPORT void JNICALL
Java_com_giraffetechnology_qc_qwen_NativeMnnQwenBridge_nativeUnloadModel(
    JNIEnv* env, jobject /* thiz */, jlong handle_jlong)
{
    auto* h = reinterpret_cast<LlmHandle*>(
        static_cast<uintptr_t>(handle_jlong));
    if (!h) {
        LOGW("nativeUnloadModel: null handle, no-op");
        return;
    }
    LOGI("nativeUnloadModel: ptr=%lld", (long long)handle_jlong);
    delete h->llm;
    delete h;
}
