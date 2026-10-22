ARG WEB_IMAGE
FROM ${WEB_IMAGE}
COPY tools /usr/local/bin/
COPY licenses /opt/sweclar/licenses/media/
RUN chmod 755 /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /usr/local/bin/mediamtx && mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py browser_health.py /opt/sweclar/
ENV MTX_MOQ=no
ENV NODE_BIN=/usr/local/lib/python3.12/dist-packages/playwright/driver/node
ENV PLAYWRIGHT_NODE_MODULE=/usr/local/lib/python3.12/dist-packages/playwright/driver/package
