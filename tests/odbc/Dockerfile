# The image tests/odbc/run.sh runs the odbc tests in: uv (which fetches the Python the repo names), the Docker CLI, unixODBC and psqlODBC.
FROM ghcr.io/astral-sh/uv:bookworm-slim
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker
RUN apt-get update && apt-get install -y --no-install-recommends unixodbc odbc-postgresql \
 && rm -rf /var/lib/apt/lists/*
# the repo is mounted from the host: the environment and the bytecode stay out of it
ENV UV_PROJECT_ENVIRONMENT=/venv PYTHONDONTWRITEBYTECODE=1
