"""The `rest` connector: flat JSON objects over HTTP, page by page (spec tests 5 to 10)."""
import importlib.metadata
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

from rowvioli.connectors import rest
from test_columns_go_and_come import columns, log_replays

TOKEN = "Marke-0815-geheim"
READINGS = [
    [{"station": "a", "time": "2026-01-01T10:00:00Z", "temp": 1.5, "day": "2026-01-01", "ok": True, "n": 1, "x": 9, "at": None}],
    [{"station": "b", "time": "2026-01-01T11:00:00+01:00", "day": "2026-01-02", "ok": False, "n": 2, "temp": None, "at": None}],
    [{"station": "c", "time": "2026-01-01T12:00:00Z", "temp": 3.0, "day": "2026-01-03", "ok": True, "n": 3, "at": None}],
]
BAD = {"/bad": [{"station": "a", "n": "abc"}], "/fraction": [{"station": "a", "n": 1.5}],
       "/bool-int": [{"station": "a", "n": True}], "/bool-float": [{"station": "a", "temp": True}],
       "/zone": [{"station": "a", "at": "2026-01-01T10:00:00Z"}], "/html": "<html>no json</html>",
       "/int-float": [{"station": "a", "temp": 2}], "/nulls": [{"station": "a", "n": None}],
       "/renamed": [{"station": "a", "m": 1}, {"station": "b", "m": 2}]}
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
            elif url.path in ("/wrapped", "/nested"):
                page = int(query.get("page", ["1"])[0])
                rows = READINGS[page - 1] if page <= len(READINGS) else []
                body = {"data": rows} if url.path == "/wrapped" else {"result": {"items": rows}}
            elif url.path == "/slow":
                time.sleep(6)  # longer than httpx's default of 5 seconds
                body = [{"station": "a"}]
            elif url.path == "/denied":
                code = 401
            elif url.path == "/v1/items":
                code = 404
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
    assert api.target("select distinct driver_version from _rowvioli.runs") == [
        (f"httpx {importlib.metadata.version('httpx')}",)]  # story 38


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
    ('path = "/open", columns = { station = "text" }, pagee = "p"',
     "the option pagee is not one of the rest connector's; it knows path, columns, page, rows"),
    ('path = "/int-float", page = "page", columns = { station = "text" }', "does not page"),  # ignores the page
])
def test_bad_types_values_and_responses_fail_the_run_naming_the_cause(api, options, cause):
    r, _ = load(api, f'a = {{ key = ["station"], {options} }}')
    assert r.returncode == 1
    assert cause in reason(api)


def test_an_int_into_float8_is_fine(api):
    r, _ = load(api, 'a = { key = ["station"], path = "/int-float", columns = { station = "text", temp = "float8" } }')
    assert r.returncode == 0, r.stdout


def listener():
    """A second server that records every request it gets."""
    got = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            got.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'[{"station": "evil"}]')

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, got


@pytest.mark.parametrize("path", [".evil.com/x", "@127.0.0.1:{port}/x"])
def test_a_path_that_leaves_the_connections_host_fails_the_run_and_the_other_host_sees_nothing(api, path):
    server, got = listener()
    definition(api, 'a = { key = ["station"], path = "/open", columns = { station = "text" } }')
    assert api.run("apply", "sources").returncode == 0
    # a writer of the target bypasses apply
    api.target("update _rowvioli.tables set options = jsonb_set(options, '{path}', to_jsonb(%s::text))",
               [path.format(port=server.server_port)])
    r = api.run("run")
    server.shutdown()
    assert r.returncode == 1
    assert "path" in reason(api)
    assert got == []
    assert TOKEN not in r.stdout + r.stderr + reason(api)


def test_apply_rejects_a_rest_path_without_a_leading_slash(api):
    definition(api, 'a = { key = ["station"], path = "readings", columns = { station = "text" } }')
    r = api.run("apply", "sources")
    assert r.returncode == 1
    assert "path" in r.stderr


def test_a_token_with_a_trailing_newline_shows_nowhere(api):
    definition(api, 'a = { key = ["station"], path = "/open", columns = { station = "text" } }', token=False)
    toml = api.dir / "sources/weather.toml"
    toml.write_text(toml.read_text().replace("[weather.tables]", 'token = "$TOK"\n[weather.tables]', 1))
    env = {"TOK": "Geheim-0815-xyz\n"}
    out = [api.run("apply", "sources", env=env), api.run("run", env=env), api.run("status", env=env)]
    assert out[1].returncode == 1
    seen = "".join(r.stdout + r.stderr for r in out) + str(api.target(
        "select reason from _rowvioli.tables union all select reason from _rowvioli.runs"))
    assert "Geheim-0815-xyz" not in seen


def test_a_token_outside_ascii_fails_without_showing_a_character_of_it():
    with pytest.raises(Exception) as e:
        list(rest.read({"url": "http://127.0.0.1:1", "token": "tökén"}, "a", {"path": "/x", "columns": {}}))
    assert str(e.value) == "a: the token holds a character outside ASCII"


def test_a_type_mismatch_names_table_column_and_type_but_not_the_value(api):
    r, _ = load(api, 'a = { key = ["station"], path = "/bad", columns = { station = "text", n = "int8" } }')
    assert r.returncode == 1
    assert reason(api) == ("a: column n is not int8 in every row; change the value at the source, or its type under "
                           "columns")  # as the file connector says it
    assert "abc" not in reason(api) + r.stdout + r.stderr


LAST = ('select _op, "column", mirror, was, "by" from _rowvioli.columns__log where _run = (select max(run) from '
        '_rowvioli.runs) order by "column"')


def test_F1_a_column_left_out_of_columns_leaves_the_mirror_and_one_absent_from_every_row_is_empty(api):
    load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text", n = "int8" } }')
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text" } }')
    assert r.returncode == 0, r.stdout
    # the definition is the catalog: n leaves the mirror as a column a database drops, its values stay in the log
    assert columns(api, "raw_weather.a") == ["station"]
    assert api.target("select n from raw_weather.a__history where station = 'a' order by _valid_from") == [
        (1,), (None,)]
    assert api.target(LAST) == [("U", "n", False, None, "definition")]
    log_replays(api, "raw_weather.a")
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, 'a = { key = ["station"], path = "/renamed", columns = { station = "text", n = "int8" } }')
    assert r.returncode == 0, r.stdout
    assert api.target("select station, n from raw_weather.a order by 1") == [("a", None), ("b", None)]
    log_replays(api, "raw_weather.a")


def test_a_column_a_person_added_to_the_mirror_is_not_taken_for_one_left_out_of_columns_and_stops_the_run(api):
    load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text" } }')  # story 8, G1
    api.target("alter table raw_weather.a add column memo text")
    api.target("update raw_weather.a set memo = 'mine'")
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text" } }')
    assert r.returncode == 1
    assert reason(api).startswith("column memo of the mirror is not in the change log")
    assert api.target("select memo from raw_weather.a") == [("mine",)]


def test_F4_B11_a_type_under_columns_changed_to_another_family_goes_and_comes_by_definition(api):
    table = 'a = {{ key = ["station"], path = "/readings", columns = {{ station = "text", day = "{}" }} }}'
    load(api, table.format("date"))
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, table.format("text"))
    assert r.returncode == 0, r.stdout
    assert api.target("select station, day from raw_weather.a") == [("a", "2026-01-01")]
    run = api.target("select max(run) from _rowvioli.runs")[0][0]
    assert columns(api, "raw_weather.a__log")[-2:] == [f"day__{run}", "day"]  # the old values stay in the log
    assert api.target(LAST) == [("U", "day", True, None, "definition"), ("I", f"day__{run}", False, "day", "definition")]
    log_replays(api, "raw_weather.a")


@pytest.mark.parametrize("columns, why", [
    ('{ station = "text", day = "text" }', "column day has changed its type from date to text, and no change log keeps "
                                           "its values, so a person drops it and the next run adds "
                                           'it anew: ALTER TABLE "raw_weather"."a" DROP COLUMN "day"'),
    ('{ station = "text" }', "column day is missing in the source, and no change log keeps its values, "
                             'so a person drops it: ALTER TABLE "raw_weather"."a" DROP COLUMN "day"')])
def test_without_a_change_log_a_column_whose_type_or_presence_columns_changes_stops_and_says_how_to_drop_it(
        api, columns, why):
    load(api, 'a = { key = ["station"], log = false, path = "/readings", columns = { station = "text", day = "date" } }')
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, f'a = {{ key = ["station"], log = false, path = "/readings", columns = {columns} }}')
    assert r.returncode == 1
    assert reason(api) == why
    api.target('ALTER TABLE "raw_weather"."a" DROP COLUMN "day"')  # the way out
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, f'a = {{ key = ["station"], log = false, path = "/readings", columns = {columns} }}')
    assert r.returncode == 0, r.stdout


def test_a_column_present_as_null_stays_null(api):
    r, _ = load(api, 'a = { key = ["station"], path = "/nulls", columns = { station = "text", n = "int8" } }')
    assert r.returncode == 0, r.stdout
    assert api.target("select n from raw_weather.a") == [(None,)]


def test_the_mirror_columns_follow_the_order_of_columns(api):
    load(api, 'a = { key = ["station"], path = "/readings", columns = { n = "int8", ok = "bool", station = "text", '
              'day = "date" } }')
    assert [c for (c,) in api.target("select column_name from information_schema.columns where table_schema = "
                                     "'raw_weather' and table_name = 'a' order by ordinal_position")] == [
        "n", "ok", "station", "day"]


@pytest.mark.parametrize("options", ['path = "/empty", page = "page"', 'path = "/empty"'])
def test_a_new_empty_table_is_mirrored_empty(api, options):
    r, _ = load(api, f'a = {{ key = ["station"], {options}, columns = {{ station = "text" }} }}')
    assert r.returncode == 0, r.stdout
    assert api.target("select count(*) from raw_weather.a") == [(0,)]


def test_a_mirror_with_rows_whose_source_delivers_zero_rows_still_fails(api):
    load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text" } }')
    api.target("update _rowvioli.tables set options = jsonb_set(options, '{path}', '\"/empty\"'), "
               "requested_at = now()")
    assert api.run("run").returncode == 1
    assert "zero rows" in reason(api)


def test_an_answer_slower_than_five_seconds_loads(api):
    r, _ = load(api, 'a = { key = ["station"], path = "/slow", columns = { station = "text" } }')
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("path, rows, page", [("/wrapped", "data", True), ("/nested", "result.items", True),
                                              ("/wrapped", "data", False), ("/nested", "result.items", False)])
def test_rows_names_the_field_that_holds_the_array_paged_and_unpaged(api, path, rows, page):
    paging = ', page = "page"' if page else ""
    r, answer = load(api, f'a = {{ key = ["station"], path = "{path}", rows = "{rows}"{paging}, columns = {COLUMNS} }}')
    assert r.returncode == 0, r.stdout
    assert answer["raw_weather.a"]["inserted"] == (3 if page else 1)


@pytest.mark.parametrize("path, rows", [("/wrapped", "nope"), ("/nested", "result.nope"), ("/nested", "data"),
                                        ("/readings", "data"), ("/nested", "result")])
def test_a_missing_rows_field_fails_the_run_naming_rows_and_keeps_the_mirror(api, path, rows):
    load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text" } }')
    before = api.target("select * from raw_weather.a")
    api.target("update _rowvioli.tables set options = jsonb_set(jsonb_set(options, '{path}', to_jsonb(%s::text)), "
               "'{rows}', to_jsonb(%s::text)), requested_at = now()", [path, rows])
    assert api.run("run").returncode == 1
    assert "rows" in reason(api)
    assert api.target("select * from raw_weather.a") == before


@pytest.mark.parametrize("rows", ['""', "5", "true"])
def test_rows_that_is_no_field_name_fails_the_run_naming_the_option(api, rows):
    r, _ = load(api, f'a = {{ key = ["station"], path = "/readings", rows = {rows}, columns = {COLUMNS} }}')
    assert r.returncode == 1 and reason(api).endswith("a: the option rows must be a field name"), reason(api)


def test_renamed_with_a_column_taken_out_of_columns_in_the_same_apply(api):  # ticket 14, item 3
    load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text", n = "int8", day = "date" } }')
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, 'a = { key = ["station"], path = "/renamed", columns = { station = "text", m = "int8" }, '
                     'renamed = { m = "n" } }')
    assert r.returncode == 0, r.stdout
    assert columns(api, "raw_weather.a") == ["station", "m"]
    assert api.target("select station, m from raw_weather.a order by 1") == [("a", 1), ("b", 2)]
    # the rename writes no row: a is a U for day, which leaves the mirror, and b is new
    assert api.target("select _op, station, m from raw_weather.a__log where _run = (select max(run) from "
                      "_rowvioli.runs) order by 2, 1") == [("U", "a", 1), ("I", "b", 2)]
    assert api.target('select _op, "column", mirror, was, "by" from _rowvioli.columns__log where _run = (select '
                      'max(run) from _rowvioli.runs) order by "column"') == [
        ("U", "day", False, None, "definition"), ("I", "m", True, "n", "definition"),
        ("D", "n", True, None, "definition")]
    log_replays(api, "raw_weather.a")


def test_renamed_with_a_type_changed_to_another_family_stops_and_its_way_out_leads_out(api):  # ticket 14, item 3
    load(api, 'a = { key = ["station"], path = "/readings", columns = { station = "text", n = "int8" } }')
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, 'a = { key = ["station"], path = "/renamed", columns = { station = "text", m = "float8" }, '
                     'renamed = { m = "n" } }')
    assert r.returncode == 1
    assert reason(api) == ("column n is renamed m in the table's definition, but bigint and double precision are types "
                           "of two families, so their values are not the same: take m out of renamed")
    assert columns(api, "raw_weather.a") == ["station", "n"]
    api.target("update _rowvioli.tables set requested_at = now()")
    r, _ = load(api, 'a = { key = ["station"], path = "/renamed", columns = { station = "text", m = "float8" } }')
    assert r.returncode == 0, r.stdout
    assert columns(api, "raw_weather.a") == ["station", "m"]
    assert api.target("select station, n, m from raw_weather.a__history where _valid_to is null order by 1") == [
        ("a", None, 1.0), ("b", None, 2.0)]
    log_replays(api, "raw_weather.a")


def test_A20_a_rest_column_name_longer_than_63_bytes_fails_the_run_and_names_the_column(api):  # ticket 10 left it
    long = "c" * 64
    r, _ = load(api, f'a = {{ key = ["station"], path = "/readings", columns = {{ station = "text", '
                     f'{long} = "int8" }} }}')
    assert r.returncode == 1
    assert reason(api) == (f"column {long} of the source is longer than 63 bytes, the most Postgres keeps of a name: "
                           "give it a shorter name in the source")
    assert api.target("select to_regclass('raw_weather.a')") == [(None,)]
