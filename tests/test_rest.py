"""The `rest` connector: flat JSON objects over HTTP, page by page (spec tests 5 to 10)."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

TOKEN = "Marke-0815-geheim"
READINGS = [
    [{"station": "a", "time": "2026-01-01T10:00:00Z", "temp": 1.5, "day": "2026-01-01", "ok": True, "n": 1, "x": 9}],
    [{"station": "b", "time": "2026-01-01T11:00:00+01:00", "day": "2026-01-02", "ok": False, "n": 2}],
    [{"station": "c", "time": "2026-01-01T12:00:00Z", "temp": 3.0, "day": "2026-01-03", "ok": True, "n": 3}],
]
BAD = {"/bad": [{"station": "a", "n": "abc"}], "/fraction": [{"station": "a", "n": 1.5}],
       "/bool-int": [{"station": "a", "n": True}], "/bool-float": [{"station": "a", "temp": True}],
       "/zone": [{"station": "a", "at": "2026-01-01T10:00:00Z"}], "/html": "<html>no json</html>",
       "/int-float": [{"station": "a", "temp": 2}]}
COLUMNS = ('{ station = "text", time = "timestamptz", temp = "float8", day = "date", ok = "bool", n = "int8", '
           'at = "timestamp" }')


@pytest.fixture
def api(rv):
    """init, key, and an HTTP server answering `/readings` page by page (and `/open`, `/denied`, `/object`, `/bad`);
    rv.requests records (path, query, Authorization) of every request."""
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            requests.append((url.path, {k: v[0] for k, v in query.items()}, self.headers.get("Authorization")))
            code, body = 200, []
            if url.path == "/readings":
                page = int(query.get("page", ["1"])[0])
                body = READINGS[page - 1] if page <= len(READINGS) else []
            elif url.path == "/denied":
                code = 401
            elif url.path == "/object":
                body = {"data": []}
            elif url.path in BAD:
                body = BAD[url.path]
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body.encode() if isinstance(body, str) else json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    rv.requests, rv.url = requests, f"http://127.0.0.1:{server.server_port}"
    yield rv
    server.shutdown()


def definition(rv, tables, token=True):
    rv.definition({"weather.toml": f"""
[weather]
type = "rest"
max_age = "1h"
[weather.connection]
url = "{rv.url}"
{f'token = "{TOKEN}"' if token else ''}
[weather.tables]
{tables}"""})


def load(rv, tables, token=True):
    definition(rv, tables, token)
    r = rv.run("apply", "sources")
    assert r.returncode == 0, r.stderr
    r = rv.run("run")
    assert r.stdout, r.stderr
    return r, json.loads(r.stdout)["tables"]


def reason(rv):
    return rv.target("select reason from _rowvioli.runs where reason is not null")[0][0]


def test_a_paged_endpoint_is_mirrored_completely_and_a_table_without_page_is_one_request(api):
    _, answer = load(api, f'readings = {{ key = ["station"], path = "/readings", page = "page", columns = {COLUMNS} }}\n'
                          f'single = {{ key = ["station"], path = "/readings", columns = {COLUMNS} }}\n')
    assert {t: a["inserted"] for t, a in answer.items()} == {"raw_weather.readings": 3, "raw_weather.single": 1}
    assert sorted(q["page"] for p, q, _ in api.requests if "page" in q) == ["1", "2", "3", "4"]
    assert [q for p, q, _ in api.requests].count({}) == 1


def test_named_types_arrive_unnamed_fields_are_dropped_and_missing_ones_are_null(api):
    load(api, f'readings = {{ key = ["station"], path = "/readings", page = "page", columns = {COLUMNS} }}\n')
    types = dict(api.target("select column_name, data_type from information_schema.columns "
                            "where table_schema = 'raw_weather' and table_name = 'readings'"))
    assert types == {"station": "text", "time": "timestamp with time zone", "temp": "double precision",
                     "day": "date", "ok": "boolean", "n": "bigint", "at": "timestamp without time zone"}
    rows = api.target("select station, temp, at, (time at time zone 'UTC')::text, day::text "
                      "from raw_weather.readings order by station")
    assert rows == [("a", 1.5, None, "2026-01-01 10:00:00", "2026-01-01"),
                    ("b", None, None, "2026-01-01 10:00:00", "2026-01-02"),
                    ("c", 3.0, None, "2026-01-01 12:00:00", "2026-01-03")]


@pytest.mark.parametrize("token, header", [(True, f"Bearer {TOKEN}"), (False, None)])
def test_the_token_is_a_bearer_header_and_without_token_there_is_none(api, token, header):
    load(api, 'a = { key = ["station"], path = "/open", columns = { station = "text" } }', token)
    assert api.requests[-1][2] == header


def test_a_refusal_fails_the_run_with_status_and_path_and_no_token(api):
    r, _ = load(api, 'a = { key = ["station"], path = "/denied", columns = { station = "text" } }')
    assert r.returncode == 1
    assert "401" in reason(api) and "/denied" in reason(api)
    assert TOKEN not in r.stdout + r.stderr + reason(api)


@pytest.mark.parametrize("options, cause", [
    ('path = "/open", columns = { station = "wide" }', "text"),
    ('path = "/bad", columns = { station = "text", n = "int8" }', "n"),
    ('path = "/object", columns = { station = "text" }', "array"),
    ('path = "/html", columns = { station = "text" }', "array of flat objects"),
    ('path = "/fraction", columns = { station = "text", n = "int8" }', "n"),
    ('path = "/bool-int", columns = { station = "text", n = "int8" }', "n"),
    ('path = "/bool-float", columns = { station = "text", temp = "float8" }', "temp"),
    ('path = "/zone", columns = { station = "text", at = "timestamp" }', "at"),
    ('columns = { station = "text" }', "option path"),
    ('path = "/open"', "option columns"),
    ('path = "/int-float", page = "page", columns = { station = "text" }', "does not page"),  # ignores the page
])
def test_bad_types_values_and_responses_fail_the_run_naming_the_cause(api, options, cause):
    r, _ = load(api, f'a = {{ key = ["station"], {options} }}')
    assert r.returncode == 1
    assert cause in reason(api)


def test_an_int_into_float8_is_fine(api):
    r, _ = load(api, 'a = { key = ["station"], path = "/int-float", columns = { station = "text", temp = "float8" } }')
    assert r.returncode == 0, r.stdout


def test_list_says_the_connector_cannot_list_tables(api):
    definition(api, "")
    r = api.run("list", "weather")
    assert r.returncode == 1
    assert r.stderr.strip() == "connector rest of source weather cannot list tables"
