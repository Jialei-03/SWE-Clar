ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY flutter/ /opt/flutter/
COPY pub-cache/ /opt/pub-cache/
ENV FLUTTER_ROOT=/opt/flutter PUB_CACHE=/opt/pub-cache CI=true FLUTTER_SUPPRESS_ANALYTICS=true FLUTTER_ALREADY_LOCKED=true
ENV PATH=/usr/local/bin:/opt/flutter/bin/cache/dart-sdk/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
RUN git config --system --add safe.directory /opt/flutter
RUN cd /opt/flutter/packages/flutter_tools && dart pub get --offline --enforce-lockfile
RUN dart --disable-analytics && dart --snapshot=/opt/flutter/bin/cache/flutter_tools.snapshot --snapshot-kind=app-jit --packages=/opt/flutter/packages/flutter_tools/.dart_tool/package_config.json --no-enable-mirrors /opt/flutter/packages/flutter_tools/bin/flutter_tools.dart --no-version-check --suppress-analytics --version --machine
COPY flutter-launch /usr/local/bin/flutter
COPY dart-launch /usr/local/bin/dart
RUN chmod 755 /usr/local/bin/flutter /usr/local/bin/dart
RUN cp /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py /opt/sweclar/preflight.py
COPY preflight_fixture/ /opt/sweclar/flutter-fixture/
WORKDIR /workspace
