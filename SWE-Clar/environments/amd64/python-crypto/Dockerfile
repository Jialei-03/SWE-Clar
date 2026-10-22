ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY wheels /opt/wheels
RUN python -m pip install --no-index --find-links /opt/wheels cryptography==50.0.1 cffi==2.1.1 pycparser==3.0 && rm -rf /opt/wheels && mv /opt/sweclar/preflight.py /opt/sweclar/base_preflight.py
COPY preflight.py crypto_health.py /opt/sweclar/
