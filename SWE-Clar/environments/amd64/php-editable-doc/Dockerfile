ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY wheels /opt/wheels
RUN python -m pip install --no-index --no-deps --find-links /opt/wheels python-docx==1.2.0 lxml==6.0.2 && rm -rf /opt/wheels && mv /opt/sweclar/preflight.py /opt/sweclar/base_preflight.py
COPY preflight.py docx_health.py /opt/sweclar/
