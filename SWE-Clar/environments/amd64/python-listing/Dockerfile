ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY offer_service.py events.json preflight.py /opt/sweclar/
ENV OFFER_SERVICE_URL=http://127.0.0.1:38900
