ARG WORDPRESS_IMAGE
ARG DATABASE_IMAGE
ARG BASE_IMAGE
FROM ${WORDPRESS_IMAGE} AS wordpress
RUN cp "$(php -r 'echo ini_get("extension_dir");')/mysqli.so" /mysqli.so
FROM ${DATABASE_IMAGE} AS database
FROM ${BASE_IMAGE}
COPY --from=wordpress /mysqli.so /opt/php-runtime/extensions/mysqli.so
COPY --from=wordpress /usr/src/wordpress /opt/sweclar/wordpress
COPY --from=database /usr/sbin/mariadbd /usr/sbin/mariadbd
COPY --from=database /usr/bin/mariadb-install-db /usr/bin/my_print_defaults /usr/bin/resolveip /usr/bin/
COPY --from=database /usr/share/mariadb /usr/share/mariadb
COPY --from=database /usr/lib/mysql/plugin /usr/lib/mysql/plugin
COPY --from=database /usr/lib/x86_64-linux-gnu/liburing.so.* /usr/lib/x86_64-linux-gnu/
COPY --from=database /usr/share/doc/mariadb-server/copyright /opt/sweclar/licenses/mariadb-copyright
COPY wheels /opt/wheels
RUN python -m pip install --no-index --no-deps --find-links /opt/wheels PyMySQL==1.1.1 && rm -rf /opt/wheels && sed -i 's/-d extension=gd/-d extension=gd -d extension=mysqli/' /usr/local/bin/php && mv /opt/sweclar/preflight.py /opt/sweclar/base_preflight.py
COPY database_fixture.py wordpress_fixture.py preflight.py /opt/sweclar/
