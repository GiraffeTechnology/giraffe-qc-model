# JNI bridge for on-device MNN Qwen-VL inference (padLocal).
#
# Builds libmnn_qwen_jni.so, which implements the native methods declared in
# com.giraffetechnology.qc.qwen.MnnRuntimeLoader and links against the prebuilt
# MNN libraries shipped under src/main/jniLibs/<abi>/.
#
# Headers (llm/llm.hpp, MNN/Interpreter.hpp) come from src/main/cpp/include and
# are provided by the real MNN AAR (see scripts/download_mnn_android_libs.sh).
# The --ci-stubs headers are empty and are NOT sufficient to compile this target;
# native builds require the real AAR.

cmake_minimum_required(VERSION 3.22.1)
project(mnn_qwen_jni CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(JNILIBS_DIR "${CMAKE_SOURCE_DIR}/../jniLibs/${ANDROID_ABI}")

add_library(MNN SHARED IMPORTED)
set_target_properties(MNN PROPERTIES IMPORTED_LOCATION "${JNILIBS_DIR}/libMNN.so")

add_library(MNN_Express SHARED IMPORTED)
set_target_properties(MNN_Express PROPERTIES IMPORTED_LOCATION "${JNILIBS_DIR}/libMNN_Express.so")

add_library(mnn_qwen_jni SHARED mnn_qwen_jni.cpp)

target_include_directories(mnn_qwen_jni PRIVATE "${CMAKE_SOURCE_DIR}/include")

find_library(log-lib log)

target_link_libraries(mnn_qwen_jni
    MNN
    MNN_Express
    ${log-lib})
