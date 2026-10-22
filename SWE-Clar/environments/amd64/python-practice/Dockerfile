ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py && ln -s /usr/local/lib/python3.12/dist-packages/playwright/driver/node /usr/local/bin/node
COPY ui /opt/sweclar/ui
COPY preflight.py fixture.py /opt/sweclar/
ENV UI_NODE_MODULES=/opt/sweclar/ui/node_modules ESBUILD_BINARY_PATH=/opt/sweclar/ui/node_modules/@esbuild/linux-x64/bin/esbuild PRACTICE_CONFIG=/tmp/sweclar-practice/config.json PRACTICE_ASSETS=/tmp/sweclar-practice PRACTICE_DATABASE=/workspace/practice.sqlite
