# A worker image: the program and the operator's drivers. There is no official image (decision 16).
#   docker build -f Dockerfile -t etl-worker .
#   docker run -e ROWVIOLI_TARGET_URL -e ROWVIOLI_KEY_FILE=/run/secrets/worker.key etl-worker
FROM python:3.12-slim

# The vendors' drivers go here, for example:
# RUN apt-get update && apt-get install -y --no-install-recommends unixodbc && rm -rf /var/lib/apt/lists/*

# The program with the connectors this worker needs, for example "rowvioli[file] rowvioli-weather".
# The build context is mounted at /src, so PACKAGE=/src installs a checkout of rowvioli instead.
ARG PACKAGE=rowvioli
RUN --mount=type=bind,target=/src,rw pip install --no-cache-dir $PACKAGE

RUN useradd --create-home etl
USER etl
WORKDIR /home/etl
CMD ["rowvioli", "work", "--slots", "4"]
