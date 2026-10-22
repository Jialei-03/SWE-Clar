ARG PHP_IMAGE
ARG WEB_IMAGE
FROM ${PHP_IMAGE} AS php_runtime
RUN set -eu; mkdir -p /bundle/lib /bundle/extensions /bundle/licenses; \
    ext="$(php -r 'echo ini_get("extension_dir");')"; \
    cp /usr/local/bin/php /bundle/php; \
    cp "$ext/bcmath.so" "$ext/gd.so" /bundle/extensions/; \
    (ldd /usr/local/bin/php; ldd "$ext/bcmath.so"; ldd "$ext/gd.so") \
      | awk '$2 == "=>" && $3 ~ /^\// {print $3} $1 ~ /^\// {print $1}' \
      | sort -u > /bundle/library-paths.txt; \
    while IFS= read -r library; do cp -L "$library" "/bundle/lib/$(basename "$library")"; done < /bundle/library-paths.txt; \
    find /usr/share/doc -name copyright -type f -exec cp --parents '{}' /bundle/licenses/ ';'; \
    tar -xOf /usr/src/php.tar.xz --wildcards '*/LICENSE' > /bundle/licenses/PHP-LICENSE
FROM ${WEB_IMAGE}
COPY --from=php_runtime /bundle /opt/php-runtime
COPY php /usr/local/bin/php
COPY tcpdf.tar.gz /tmp/tcpdf.tar.gz
RUN chmod 755 /usr/local/bin/php && mkdir -p /opt/sweclar/tcpdf && \
    echo '8055b09c4aaebe437becfb60d7dc43268211ff971963a4fe7d5f1e1ad85a3b16  /tmp/tcpdf.tar.gz' | sha256sum -c - && \
    tar -xzf /tmp/tcpdf.tar.gz --strip-components=1 -C /opt/sweclar/tcpdf && rm /tmp/tcpdf.tar.gz
ENV TCPDF_ROOT=/opt/sweclar/tcpdf

COPY wheelhouse /tmp/wheelhouse
COPY requirements.txt /tmp/document-requirements.txt
RUN python -m pip install --no-index --no-deps --require-hashes --find-links=/tmp/wheelhouse -r /tmp/document-requirements.txt && rm -r /tmp/wheelhouse /tmp/document-requirements.txt
RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py document_probe.php /opt/sweclar/
