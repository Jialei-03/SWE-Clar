ARG WEB_IMAGE
FROM ${WEB_IMAGE}
COPY cesium /opt/sweclar/cesium
RUN mv /opt/sweclar/preflight.py /opt/sweclar/vision_preflight.py
COPY preflight.py cesium_probe.py /opt/sweclar/
ENV CESIUM_ASSET_DIR=/opt/sweclar/cesium/Build/Cesium
