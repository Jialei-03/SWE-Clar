ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY jre/ /opt/jre/
COPY emulator.jar /opt/firestore/emulator.jar
RUN cp /opt/sweclar/preflight.py /opt/sweclar/flutter_preflight.py
COPY preflight.py firestore_service.py development_seed.json /opt/sweclar/
COPY preflight_fixture/ /opt/sweclar/firestore-fixture/
WORKDIR /workspace
