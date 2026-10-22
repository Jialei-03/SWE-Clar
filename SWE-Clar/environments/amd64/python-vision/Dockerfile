ARG WEB_IMAGE
FROM ${WEB_IMAGE}
COPY packages /tmp/vision-packages
COPY requirements.txt /tmp/vision-requirements.txt
RUN dpkg -i /tmp/vision-packages/*.deb && \
    python -m pip install --no-index --no-deps --require-hashes --find-links=/tmp/vision-packages -r /tmp/vision-requirements.txt && \
    rm -rf /tmp/vision-packages /tmp/vision-requirements.txt
RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py /opt/sweclar/preflight.py
ENV OMP_THREAD_LIMIT=2
