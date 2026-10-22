ARG BASE_IMAGE=sweclar-python-web-base:65af077b23a0
FROM ${BASE_IMAGE}
COPY wheelhouse /wheelhouse
COPY requirements.txt /requirements.txt
RUN python -m pip install --no-index --find-links=/wheelhouse --require-hashes -r /requirements.txt && rm -rf /wheelhouse /requirements.txt
COPY harness.py preflight.py /opt/sweclar/
RUN mkdir -p /private /workspace /public_tests && chmod 700 /private && chmod 1777 /workspace
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
