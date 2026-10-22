ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY sdk /opt/sweclar/sdk
RUN ln -s /usr/local/lib/python3.12/dist-packages/playwright/driver/node /usr/local/bin/node && mv /opt/sweclar/preflight.py /opt/sweclar/vision_preflight.py
ENV NODE_PATH=/opt/sweclar/sdk/node_modules
COPY preflight.py /opt/sweclar/preflight.py
