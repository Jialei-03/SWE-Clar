ARG WEB_IMAGE
FROM ${WEB_IMAGE}
COPY packages /tmp/report-packages
COPY requirements.txt /tmp/report-requirements.txt
RUN python -m pip install --no-index --no-deps --require-hashes --find-links=/tmp/report-packages -r /tmp/report-requirements.txt && rm -rf /tmp/report-packages /tmp/report-requirements.txt
RUN mv /opt/sweclar/preflight.py /opt/sweclar/vision_preflight.py
COPY preflight.py report_probe.py /opt/sweclar/
