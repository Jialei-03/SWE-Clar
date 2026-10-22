ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY watch_service.py fixtures.json preflight.py /opt/sweclar/
ENV WATCH_SERVICE_URL=http://127.0.0.1:38920
