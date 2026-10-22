ARG WEB_IMAGE
FROM ${WEB_IMAGE}
COPY wheels /tmp/comfy-wheels
COPY requirements.txt /tmp/comfy-requirements.txt
RUN python -m pip install --no-index --no-deps --require-hashes --find-links=/tmp/comfy-wheels -r /tmp/comfy-requirements.txt && rm -rf /tmp/comfy-wheels /tmp/comfy-requirements.txt
COPY comfy /opt/comfy
COPY licenses /opt/sweclar/model-licenses
COPY models /opt/comfy/models
RUN mv /opt/sweclar/preflight.py /opt/sweclar/vision_preflight.py
COPY preflight.py comfy_probe.py /opt/sweclar/
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
