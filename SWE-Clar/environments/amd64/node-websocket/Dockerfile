ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY modules /opt/sweclar/websocket
ENV NODE_PATH=/opt/sweclar/websocket/node_modules:/opt/sweclar/sdk/node_modules
COPY preflight.py /opt/sweclar/preflight.py
COPY capability.cjs /opt/sweclar/capability.cjs
