FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY backend/pom.xml pom.xml
COPY backend/src src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:21-jre
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/fleet-venv \
    && /opt/fleet-venv/bin/pip install --no-cache-dir "python-dotenv>=1.0,<2" "colab-cli>=0.1" \
    && groupadd --system fleet \
    && useradd --system --gid fleet --home-dir /home/fleet --create-home fleet \
    && mkdir -p /var/lib/fleet/runs \
    && chown -R fleet:fleet /var/lib/fleet /home/fleet

COPY --from=build /build/target/fleet-backend-*.jar /app/fleet-backend.jar
ENV PATH="/opt/fleet-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLEET_PYTHON_BIN=/opt/fleet-venv/bin/python \
    FLEET_REPO_ROOT=/opt/fleet/repo \
    FLEET_RUNS_DIR=/var/lib/fleet/runs

USER fleet
WORKDIR /opt/fleet/repo
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["/opt/fleet-venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).read()"]
ENTRYPOINT ["java", "-jar", "/app/fleet-backend.jar"]
