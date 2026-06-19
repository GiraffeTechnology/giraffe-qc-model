# MNN Android Distribution

This directory holds MNN Android headers and (optionally) pre-built libraries
required to build the native inference bridge.

**This directory is git-ignored.** Run `scripts/download_mnn_android_libs.sh`
to populate it after a fresh checkout.

## Expected layout

```
mnn_android/
  include/
    llm/
      llm.hpp          <- MNN LLM inference API (Llm::createLLM, load, response_nohistory)
    MNN/
      Interpreter.hpp  <- Core MNN headers
      ...
  libs/                <- Optional: place .so here if NOT using jniLibs/
    arm64-v8a/
      libMNN.so
      libMNN_Express.so
```

The pre-built `.so` files for APK packaging go in:
```
apps/android-qc/app/src/main/jniLibs/arm64-v8a/
```

Gradle automatically packages `jniLibs/` into the APK.
CMakeLists.txt links against them from the same location.

## Quick setup

```bash
bash scripts/download_mnn_android_libs.sh
```

## Manual build

Build MNN 3.x for Android with LLM support:

```bash
git clone https://github.com/alibaba/MNN.git --depth 1
cd MNN && mkdir build_android && cd build_android
cmake .. \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-26 \
  -DMNN_BUILD_FOR_ANDROID=ON \
  -DMNN_BUILD_LLM=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel
cp libMNN.so libMNN_Express.so \
  ../apps/android-qc/app/src/main/jniLibs/arm64-v8a/
cp ../transformers/llm/export/llm.hpp \
  ../apps/android-qc/mnn_android/include/llm/
cp -r ../include/. ../apps/android-qc/mnn_android/include/
```

See `docs/PAD_LOCAL_MNN_DEPLOYMENT.md` for the complete deployment guide.
