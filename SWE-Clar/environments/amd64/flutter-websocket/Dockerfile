ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY modules /opt/sweclar/websocket
RUN ln -s /usr/local/lib/python3.12/dist-packages/playwright/driver/node /usr/local/bin/node && mv /opt/sweclar/preflight.py /opt/sweclar/flutter_preflight.py
ENV NODE_PATH=/opt/sweclar/websocket/node_modules
COPY capability.cjs preflight.py /opt/sweclar/
