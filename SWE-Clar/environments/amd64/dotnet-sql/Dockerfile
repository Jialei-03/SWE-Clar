ARG DATABASE_IMAGE
ARG BASE_IMAGE
FROM ${DATABASE_IMAGE} AS database
FROM ${BASE_IMAGE}
COPY --from=database /usr/sbin/mariadbd /usr/sbin/mariadbd
COPY --from=database /usr/bin/mariadb-install-db /usr/bin/my_print_defaults /usr/bin/resolveip /usr/bin/
COPY --from=database /usr/share/mariadb /usr/share/mariadb
COPY --from=database /usr/lib/mysql/plugin /usr/lib/mysql/plugin
COPY --from=database /usr/lib/x86_64-linux-gnu/liburing.so.* /usr/lib/x86_64-linux-gnu/
COPY --from=database /usr/share/doc/mariadb-server/copyright /opt/sweclar/licenses/mariadb-copyright
COPY dotnet-sdk.tar.gz /tmp/dotnet-sdk.tar.gz
RUN mkdir -p /opt/dotnet && tar -xzf /tmp/dotnet-sdk.tar.gz -C /opt/dotnet && rm /tmp/dotnet-sdk.tar.gz && ln -s /opt/dotnet/dotnet /usr/local/bin/dotnet
COPY wheels /tmp/wheels
RUN python -m pip install --no-index --find-links=/tmp/wheels cryptography==44.0.2 cffi==1.17.1 pycparser==2.22 PyMySQL==1.1.1 && rm -rf /tmp/wheels
COPY nuget /opt/sweclar/nuget-feed
COPY NuGet.Config /opt/sweclar/NuGet.Config
COPY probe /tmp/probe
ENV DOTNET_ROOT=/opt/dotnet DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1 NUGET_PACKAGES=/opt/sweclar/nuget-cache
RUN dotnet restore /tmp/probe/Probe.csproj --configfile /opt/sweclar/NuGet.Config && dotnet build /tmp/probe/Probe.csproj --no-restore -o /tmp/probe-output && dotnet /tmp/probe-output/Probe.dll && rm -rf /tmp/probe /tmp/probe-output && chmod -R a+rX /opt/sweclar/nuget-cache

RUN mv /opt/sweclar/preflight.py /opt/sweclar/web_preflight.py
COPY preflight.py database_fixture.py check_database.py /opt/sweclar/
COPY probe /opt/sweclar/dotnet-probe
COPY licenses/liburing-copyright /opt/sweclar/licenses/liburing-copyright
