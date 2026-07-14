cmake_minimum_required(VERSION 3.18)
project(giraffe_mnn_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(MNN_ROOT "" CACHE PATH "Root of the pinned MNN SDK for Xavier")
if(NOT MNN_ROOT)
  message(FATAL_ERROR "Set MNN_ROOT to the pinned Xavier MNN SDK")
endif()

find_path(MNN_LLM_INCLUDE_DIR llm/llm.hpp HINTS "${MNN_ROOT}/include")
find_library(MNN_LIBRARY MNN HINTS "${MNN_ROOT}/lib")
find_library(MNN_EXPRESS_LIBRARY MNN_Express HINTS "${MNN_ROOT}/lib")

if(NOT MNN_LLM_INCLUDE_DIR OR NOT MNN_LIBRARY OR NOT MNN_EXPRESS_LIBRARY)
  message(FATAL_ERROR "Pinned MNN headers/libraries were not found under MNN_ROOT")
endif()

add_library(giraffe_mnn_bridge SHARED giraffe_mnn_bridge.cpp)
target_include_directories(giraffe_mnn_bridge PRIVATE "${MNN_LLM_INCLUDE_DIR}")
target_link_libraries(giraffe_mnn_bridge PRIVATE "${MNN_LIBRARY}" "${MNN_EXPRESS_LIBRARY}")
target_compile_options(giraffe_mnn_bridge PRIVATE -Wall -Wextra -Wpedantic)
