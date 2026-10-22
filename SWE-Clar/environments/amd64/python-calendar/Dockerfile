ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN cp /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py /opt/sweclar/preflight.py

ENV HOME=/tmp XDG_CONFIG_HOME=/tmp/sweclar-browser-config XDG_CACHE_HOME=/tmp/sweclar-browser-cache
