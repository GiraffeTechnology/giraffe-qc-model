// JNI bridge: on-device MNN Qwen-VL inference for the padLocal edition.
//
// Implements the three native methods declared in
//   com.giraffetechnology.qc.qwen.MnnRuntimeLoader
// against the MNN Transformer LLM engine (llm/llm.hpp) shipped in the MNN AAR.
//
// ── UNVERIFIED SCAFFOLD ─────────────────────────────────────────────────────
// This file is written against the documented MNN Transformer::Llm interface but
// has NOT been compiled or run on-device in this workspace (no Android NDK / no
// real MNN AAR available here). The exact method names/signatures of the pinned
// MNN release must be reconciled before use; every such call is flagged with
// `// MNN-API:` so the integrator can confirm it against the linked headers.
// Kotlin keeps MnnRuntimeLoader.JNI_INFERENCE_WIRED = false until this bridge is
// built with the real AAR and verified on the OPPO PKB110, so the app fails
// closed until then.
// ────────────────────────────────────────────────────────────────────────────

#include <jni.h>
#include <android/log.h>

#include <memory>
#include <sstream>
#include <string>
#include <vector>
#include <sys/stat.h>

// From the real MNN AAR (src/main/cpp/include). The --ci-stubs header is empty
// and will not compile this translation unit — the real AAR is required.
#include <llm/llm.hpp>

using MNN::Transformer::Llm;

#define LOG_TAG "MnnQwenJni"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

namespace {

/**
 * Owns a loaded Llm instance. The Kotlin side treats the pointer to this struct
 * as an opaque non-zero handle; 0 always means "not loaded".
 */
struct QwenSession {
    std::unique_ptr<Llm> llm;
    std::string modelDir;
};

bool fileExists(const std::string& path) {
    struct stat st {};
    return ::stat(path.c_str(), &st) == 0;
}

std::string jstr(JNIEnv* env, jstring s) {
    if (s == nullptr) return {};
    const char* chars = env->GetStringUTFChars(s, nullptr);
    std::string out(chars ? chars : "");
    if (chars) env->ReleaseStringUTFChars(s, chars);
    return out;
}

// ── Minimal JSON string reading ─────────────────────────────────────────────
// The request is produced by MnnQwenInspector.buildRequestJson with keys
// "prompt" (string) and "images" (array of objects each with a "path" string).
// We only need those, so a focused reader (with correct escape handling) avoids
// pulling in a JSON dependency.

// Reads a JSON string token assuming json[i] == '"'. Advances i past the close
// quote. Returns the unescaped contents.
std::string readJsonStringAt(const std::string& json, size_t& i) {
    std::string out;
    if (i >= json.size() || json[i] != '"') return out;
    ++i;  // skip opening quote
    while (i < json.size()) {
        char c = json[i++];
        if (c == '"') break;
        if (c == '\\' && i < json.size()) {
            char e = json[i++];
            switch (e) {
                case 'n': out.push_back('\n'); break;
                case 't': out.push_back('\t'); break;
                case 'r': out.push_back('\r'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case '/': out.push_back('/'); break;
                case '\\': out.push_back('\\'); break;
                case '"': out.push_back('"'); break;
                case 'u': {
                    if (i + 4 <= json.size()) {
                        unsigned code = std::stoul(json.substr(i, 4), nullptr, 16);
                        i += 4;
                        // Basic BMP → UTF-8 (sufficient for our ASCII-heavy JSON).
                        if (code < 0x80) {
                            out.push_back(static_cast<char>(code));
                        } else if (code < 0x800) {
                            out.push_back(static_cast<char>(0xC0 | (code >> 6)));
                            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                        } else {
                            out.push_back(static_cast<char>(0xE0 | (code >> 12)));
                            out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
                            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                        }
                    }
                    break;
                }
                default: out.push_back(e); break;
            }
        } else {
            out.push_back(c);
        }
    }
    return out;
}

// Returns the string value for the first top-level-ish occurrence of "key".
std::string jsonStringField(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t k = json.find(needle);
    if (k == std::string::npos) return {};
    size_t colon = json.find(':', k + needle.size());
    if (colon == std::string::npos) return {};
    size_t q = json.find('"', colon + 1);
    if (q == std::string::npos) return {};
    return readJsonStringAt(json, q);
}

// Collects every "path" string value (the image references).
std::vector<std::string> jsonImagePaths(const std::string& json) {
    std::vector<std::string> paths;
    const std::string needle = "\"path\"";
    size_t pos = 0;
    while ((pos = json.find(needle, pos)) != std::string::npos) {
        size_t colon = json.find(':', pos + needle.size());
        if (colon == std::string::npos) break;
        size_t q = json.find('"', colon + 1);
        if (q == std::string::npos) break;
        paths.push_back(readJsonStringAt(json, q));
        pos = q;
    }
    return paths;
}

}  // namespace

extern "C" {

/**
 * Loads the Qwen-VL model at `modelDir`. Requires both the LLM and visual
 * weights on disk. Returns a non-zero handle on success, 0 on any failure.
 */
JNIEXPORT jlong JNICALL
Java_com_giraffetechnology_qc_qwen_MnnRuntimeLoader_nativeLoadModel(
        JNIEnv* env, jobject /*thiz*/, jstring jModelDir) {
    const std::string modelDir = jstr(env, jModelDir);
    if (modelDir.empty()) {
        LOGE("nativeLoadModel: empty modelDir");
        return 0;
    }
    // Both weights are mandatory for a vision-language pass (Kotlin already
    // presence-checks these; re-check defensively before touching native).
    if (!fileExists(modelDir + "/llm.mnn.weight") ||
        !fileExists(modelDir + "/visual.mnn.weight")) {
        LOGE("nativeLoadModel: missing llm/visual weights under %s", modelDir.c_str());
        return 0;
    }

    // MNN LLM loads via a config file. Prefer a provided config.json; otherwise
    // fall back to the directory (recent MNN accepts the model dir directly).
    std::string configPath = modelDir + "/config.json";
    if (!fileExists(configPath)) configPath = modelDir;

    // MNN-API: Llm::createLLM(config) + load(). Confirm names against the AAR.
    std::unique_ptr<Llm> llm(Llm::createLLM(configPath));
    if (!llm) {
        LOGE("nativeLoadModel: createLLM returned null for %s", configPath.c_str());
        return 0;
    }
    llm->load();  // MNN-API: throws or sets internal state on failure.

    auto* session = new QwenSession{std::move(llm), modelDir};
    LOGI("nativeLoadModel: loaded from %s", modelDir.c_str());
    return reinterpret_cast<jlong>(session);
}

/**
 * Runs one visual+LLM pass. `requestJson` carries image references + the prompt
 * (built by MnnQwenInspector). Returns the model's raw text output.
 */
JNIEXPORT jstring JNICALL
Java_com_giraffetechnology_qc_qwen_MnnRuntimeLoader_nativeRunInference(
        JNIEnv* env, jobject /*thiz*/, jlong ptr, jstring jRequestJson) {
    auto* session = reinterpret_cast<QwenSession*>(ptr);
    if (session == nullptr || !session->llm) {
        LOGE("nativeRunInference: null session");
        return env->NewStringUTF("");
    }
    const std::string request = jstr(env, jRequestJson);
    const std::string prompt = jsonStringField(request, "prompt");
    const std::vector<std::string> images = jsonImagePaths(request);

    // mnn-llm embeds images inline via <img>path</img> tags before the text.
    std::string multimodalPrompt;
    for (const auto& img : images) {
        multimodalPrompt += "<img>" + img + "</img>\n";
    }
    multimodalPrompt += prompt;

    std::ostringstream oss;
    try {
        // MNN-API: response(prompt, std::ostream*, end_with). Some releases
        // return the string directly; capture via ostream to be safe.
        session->llm->response(multimodalPrompt, &oss, nullptr);
    } catch (const std::exception& e) {
        LOGE("nativeRunInference: exception: %s", e.what());
        return env->NewStringUTF("");
    }
    return env->NewStringUTF(oss.str().c_str());
}

JNIEXPORT void JNICALL
Java_com_giraffetechnology_qc_qwen_MnnRuntimeLoader_nativeUnloadModel(
        JNIEnv* /*env*/, jobject /*thiz*/, jlong ptr) {
    auto* session = reinterpret_cast<QwenSession*>(ptr);
    if (session != nullptr) {
        delete session;  // unique_ptr<Llm> releases the native model.
        LOGI("nativeUnloadModel: released");
    }
}

}  // extern "C"
