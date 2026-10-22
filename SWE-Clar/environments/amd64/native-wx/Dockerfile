ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY debs /tmp/gui-debs
RUN DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends install /tmp/gui-debs/*.deb && rm -rf /tmp/gui-debs
RUN cp /opt/sweclar/preflight.py /opt/sweclar/native_preflight.py
COPY preflight.py gui_health.cpp /opt/sweclar/
