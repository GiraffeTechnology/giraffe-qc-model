cmake_minimum_required(VERSION 3.22.1)
project(giraffe_mnn_qwen_bridge CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# MNN Android pre-built distribution.
#
# Run scripts/download_mnn_android_libs.sh to populate:
#   apps/android-qc/mnn_android/
#     include/llm/llm.hpp          <- MNN LLM inference API
#     include/MNN/Interpreter.hpp  <- Core MNN headers
#
# Place pre-built .so files in:
#   apps/android-qc/app/src/main/jniLibs/arm64-v8a/
#     libMNN.so
#     libMNN_Express.so
#
# Gradle automatically packages files from jniLibs/ into the APK.
# CMakeLists.txt imports them for linking via IMPORTED libraries.
#
# Override MNN include path with:
#   cmake -DMNN_ANDROID_DIR=/path/to/mnn_android ...
# ---------------------------------------------------------------------------

if(NOT DEFINED MNN_ANDROID_DIR)
    # CMakeLists.txt is at app/src/main/cpp/
    # mnn_android is at   app/../mnn_android = app/src/main/cpp/../../../../mnn_android
    # i.e. apps/android-qc/mnn_android/
    set(MNN_ANDROID_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../mnn_android")
endif()

set(MNN_INCLUDE_DIR "${MNN_ANDROID_DIR}/include")
# .so files live in jniLibs/ (packaged by Gradle)
set(MNN_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../jniLibs/${ANDROID_ABI}")

message(STATUS "MNN_INCLUDE_DIR : ${MNN_INCLUDE_DIR}")
message(STATUS "MNN_LIB_DIR     : ${MNN_LIB_DIR}")

# ---------------------------------------------------------------------------
# Our JNI bridge shared library
# ---------------------------------------------------------------------------
add_library(giraffe_mnn_qwen_bridge SHARED
    native_mnn_qwen_bridge.cpp
)

target_include_directories(giraffe_mnn_qwen_bridge PRIVATE
    ${MNN_INCLUDE_DIR}
)

target_compile_options(giraffe_mnn_qwen_bridge PRIVATE
    -Wall -Wextra -Werror=return-type
    -fvisibility=hidden
)

# ---------------------------------------------------------------------------
# Import pre-built MNN shared libraries
# ---------------------------------------------------------------------------
add_library(MNN         SHARED IMPORTED)
add_library(MNN_Express SHARED IMPORTED)

set_target_properties(MNN PROPERTIES
    IMPORTED_LOCATION "${MNN_LIB_DIR}/libMNN.so"
)
set_target_properties(MNN_Express PROPERTIES
    IMPORTED_LOCATION "${MNN_LIB_DIR}/libMNN_Express.so"
)

# ---------------------------------------------------------------------------
# System libraries (always available on Android)
# ---------------------------------------------------------------------------
find_library(android-lib android)
find_library(log-lib     log)

# ---------------------------------------------------------------------------
# Link
# ---------------------------------------------------------------------------
target_link_libraries(giraffe_mnn_qwen_bridge
    MNN
    MNN_Express
    ${android-lib}
    ${log-lib}
)
