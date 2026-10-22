ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY tools/mongod /usr/local/bin/mongod
COPY licenses /opt/sweclar/licenses/mongodb/
COPY ui /opt/sweclar/portal
RUN ln -s /usr/local/lib/python3.12/dist-packages/playwright/driver/node /usr/local/bin/node
ENV NODE_PATH=/opt/sweclar/portal/node_modules MONGOD_BIN=/usr/local/bin/mongod
RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py check_mongo.py mongo_health.cjs /opt/sweclar/
