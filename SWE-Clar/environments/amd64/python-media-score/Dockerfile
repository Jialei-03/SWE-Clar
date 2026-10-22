ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY ocr-packages /tmp/ocr-packages
RUN dpkg -i /tmp/ocr-packages/*.deb && rm -rf /tmp/ocr-packages
COPY wheels /tmp/score-wheels
RUN python3 -m pip install --break-system-packages --no-index --find-links=/tmp/score-wheels mido==1.3.3 pypdf==6.10.0 packaging==26.3 pypdfium2==5.13.0 pillow==12.3.0 && rm -rf /tmp/score-wheels
COPY ui /opt/sweclar/score
RUN ln -s /usr/local/lib/python3.12/dist-packages/playwright/driver/node /usr/local/bin/node
ENV NOTATION_NODE_MODULES=/opt/sweclar/score/node_modules ESBUILD_BINARY_PATH=/opt/sweclar/score/node_modules/@esbuild/linux-x64/bin/esbuild
RUN mv /opt/sweclar/preflight.py /opt/sweclar/media_preflight.py
COPY preflight.py score_health.py /opt/sweclar/
