// Provider-neutral C ABI around MNN Transformer::Llm for the Xavier runner.
//
// This source must be compiled against the exact pinned MNN SDK deployed to
// Xavier. It has not been compiled or exercised on hardware in CI; follow
// HARDWARE_VALIDATION.md before changing hardware_validation.status.

#include <llm/llm.hpp>

#include <cstring>
#include <exception>
#include <filesystem>
#include <memory>
#include <sstream>
#include <string>

using MNN::Transformer::Llm;

namespace {
struct Runtime {
    std::unique_ptr<Llm> model;
    std::string error;
    bool ready = false;
};

void set_error(Runtime* runtime, const std::string& message) {
    if (runtime != nullptr) runtime->error = message;
}
}  // namespace

extern "C" {

void* giraffe_mnn_create(const char* model_dir) {
    auto runtime = std::make_unique<Runtime>();
    try {
        if (model_dir == nullptr || *model_dir == '\0') {
            runtime->error = "model_dir is empty";
            return runtime.release();
        }
        const std::filesystem::path root(model_dir);
        const auto config = std::filesystem::exists(root / "config.json")
            ? (root / "config.json").string()
            : root.string();
        runtime->model.reset(Llm::createLLM(config));
        if (!runtime->model) {
            runtime->error = "MNN createLLM returned null";
            return runtime.release();
        }
        // The official MNN Llm API returns false when load fails. Do not infer
        // readiness from a non-null object or model-file presence.
        if (!runtime->model->load()) {
            runtime->model.reset();
            runtime->error = "MNN Llm::load returned false";
            return runtime.release();
        }
        runtime->ready = true;
        runtime->error.clear();
    } catch (const std::exception& exc) {
        runtime->model.reset();
        runtime->ready = false;
        runtime->error = std::string("MNN model load failed: ") + exc.what();
    } catch (...) {
        runtime->model.reset();
        runtime->ready = false;
        runtime->error = "MNN model load failed: unknown native error";
    }
    return runtime.release();
}

int giraffe_mnn_is_ready(void* handle) {
    auto* runtime = static_cast<Runtime*>(handle);
    return runtime != nullptr && runtime->ready && runtime->model ? 1 : 0;
}

int giraffe_mnn_infer(
    void* handle,
    const char* image_path,
    const char* prompt,
    char* output,
    std::size_t output_capacity
) {
    auto* runtime = static_cast<Runtime*>(handle);
    if (runtime == nullptr || !runtime->ready || !runtime->model) return 1;
    if (image_path == nullptr || prompt == nullptr || output == nullptr || output_capacity == 0) {
        set_error(runtime, "invalid inference arguments");
        return 2;
    }
    try {
        const std::string multimodal_prompt =
            "<img>" + std::string(image_path) + "</img>\n" + std::string(prompt);
        std::ostringstream stream;
        runtime->model->response(multimodal_prompt, &stream, nullptr);
        const auto* context = runtime->model->getContext();
        if (context == nullptr ||
            context->status == MNN::Transformer::LlmStatus::NOT_LOADED ||
            context->status == MNN::Transformer::LlmStatus::INTERNAL_ERROR ||
            context->status == MNN::Transformer::LlmStatus::TIMEOUT ||
            context->status == MNN::Transformer::LlmStatus::USER_CANCEL) {
            set_error(runtime, "MNN response ended in an error state");
            return 5;
        }
        const std::string text = stream.str();
        if (text.size() + 1 > output_capacity) {
            set_error(runtime, "model output exceeds bridge buffer");
            return 3;
        }
        std::memcpy(output, text.c_str(), text.size() + 1);
        runtime->error.clear();
        return 0;
    } catch (const std::exception& exc) {
        set_error(runtime, std::string("MNN inference failed: ") + exc.what());
        return 4;
    } catch (...) {
        set_error(runtime, "MNN inference failed: unknown native error");
        return 4;
    }
}

const char* giraffe_mnn_last_error(void* handle) {
    auto* runtime = static_cast<Runtime*>(handle);
    return runtime == nullptr ? "invalid runtime handle" : runtime->error.c_str();
}

void giraffe_mnn_destroy(void* handle) {
    delete static_cast<Runtime*>(handle);
}

}  // extern "C"
