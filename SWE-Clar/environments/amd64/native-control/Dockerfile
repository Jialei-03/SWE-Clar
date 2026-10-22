FROM gcc@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c
USER 0:0
RUN groupadd -g 1000 candidate && useradd -m -u 1000 -g 1000 candidate && ln -s /usr/bin/python3 /usr/local/bin/python
RUN mkdir -p /workspace /private /public_tests /opt/sweclar && chmod 700 /private && chown 1000:1000 /workspace
COPY harness.py preflight.py /opt/sweclar/
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1
