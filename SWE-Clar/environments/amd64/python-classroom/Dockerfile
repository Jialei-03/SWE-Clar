FROM gcc@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c AS build
COPY source /source
COPY cmake /cmake
RUN /cmake/bin/cmake -S /source -B /build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF && /cmake/bin/cmake --build /build --target whisper-cli -j2
FROM swe-clar-base-python-classroom:locked
USER 0:0
COPY --from=build /build/bin/whisper-cli /opt/sweclar/whisper-cli
COPY --from=build /source/LICENSE /opt/sweclar/third_party/whisper-cpp-LICENSE
COPY WHISPER-MODEL-LICENSE /opt/sweclar/third_party/whisper-model-LICENSE
COPY ggml-tiny.en.bin /opt/sweclar/ggml-tiny.en.bin
COPY speech /opt/sweclar/speech
COPY preflight.py /opt/sweclar/preflight.py
ENV WHISPER_BIN=/opt/sweclar/whisper-cli WHISPER_MODEL=/opt/sweclar/ggml-tiny.en.bin
