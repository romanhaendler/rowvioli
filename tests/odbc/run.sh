#!/bin/sh
# Runs the odbc tests on a machine without an ODBC driver manager (Docker Desktop): in a container with unixODBC and
# psqlODBC, which starts the Postgres containers through the host's Docker and reaches their ports on the host.
# Arguments go to pytest.
set -e
cd "$(dirname "$0")/../.."
docker build -q -t rowvioli-odbc-test tests/odbc
docker run --rm --add-host=host.docker.internal:host-gateway -e ROWVIOLI_TEST_HOST=host.docker.internal -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:/repo" -w /repo rowvioli-odbc-test uv run --locked pytest -p no:cacheprovider tests/test_odbc.py "$@"
