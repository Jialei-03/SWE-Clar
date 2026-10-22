ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY wheels /tmp/document-wheels
RUN python -m pip install --no-index --no-deps /tmp/document-wheels/*.whl && rm -rf /tmp/document-wheels
RUN cp /opt/sweclar/preflight.py /opt/sweclar/report_preflight.py
COPY preflight.py document_health.py /opt/sweclar/
