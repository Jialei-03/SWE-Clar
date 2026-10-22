ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY feed/ /opt/sweclar/nuget-feed/
COPY probe/ /tmp/sqlite-probe/
RUN dotnet restore /tmp/sqlite-probe/Probe.csproj --configfile /opt/sweclar/NuGet.Config && dotnet build /tmp/sqlite-probe/Probe.csproj --no-restore -p:UseSharedCompilation=false -o /tmp/sqlite-app && dotnet /tmp/sqlite-app/Probe.dll && rm -rf /tmp/sqlite-probe /tmp/sqlite-app /workspace/probe.sqlite && chmod -R a+rX /opt/sweclar/nuget-cache
COPY probe/ /opt/sweclar/sqlite-probe/
COPY preflight.py /opt/sweclar/preflight.py
