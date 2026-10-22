FROM gcc@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c AS build
COPY sdk /sdk
COPY cmake /cmake
COPY sources /source
RUN /cmake/bin/cmake -S /source -B /build -DCMAKE_BUILD_TYPE=Release && /cmake/bin/cmake --build /build --target ClarPiano clar_render -j2
FROM gcc@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c
USER 0:0
RUN groupadd -g 1000 candidate && useradd -m -u 1000 -g 1000 candidate && ln -s /usr/bin/python3 /usr/local/bin/python && mkdir -p /workspace /private /public_tests /opt/sweclar/third_party && chmod 700 /private && chown 1000:1000 /workspace
COPY --from=build /build/clar_render /opt/sweclar/clar_render
COPY --from=build /build/VST3/Release/ClarPiano.vst3 /opt/sweclar/ClarPiano.vst3
COPY --from=build /sdk/LICENSE.txt /opt/sweclar/third_party/VST3-SDK-LICENSE.txt
COPY python_site /usr/local/lib/python3.11/dist-packages/
COPY render_midi.py preflight.py /opt/sweclar/
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1
