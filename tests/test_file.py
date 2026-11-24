"""The `file` connector: CSV, Excel, Parquet and JSON files and patterns from a directory (spec test 15)."""
import importlib.metadata
import json
from datetime import date, datetime
from decimal import Decimal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_columns_go_and_come import log_replays

CUSTOMERS = [(1, "Anna", 2.5), (2, "Ben", None), (3, "Cleo", 10.0)]


@pytest.fixture
def files(rv):
    """init, key, and a directory with the same three customers as CSV, Excel and Parquet."""
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    d = rv.dir / "files"
    d.mkdir()
    (d / "customers_csv.csv").write_text("customer_no;name;balance\n1;Anna;2.5\n2;Ben;\n3;Cleo;10.0\n")
    table = pa.table({"customer_no": [r[0] for r in CUSTOMERS], "name": [r[1] for r in CUSTOMERS],
                      "balance": [r[2] for r in CUSTOMERS]})
    pq.write_table(table, d / "customers_parquet.parquet")
    db = duckdb.connect()
    db.execute("INSTALL excel; LOAD excel")
    db.register("customers", table)
    db.execute(f"COPY customers TO '{d / 'customers_xlsx.xlsx'}' (FORMAT xlsx, HEADER true)")
    return rv


def load(rv, tables, options=""):
    rv.definition({"files.toml": f"""
[files]
type = "file"
max_age = "1h"
{options}
[files.connection]
path = "{rv.dir / 'files'}"
[files.tables]
{tables}"""})
    r = rv.run("apply", "sources")
    assert r.returncode == 0, r.stderr
    r = rv.run("run", "files")  # naming the source requests every table, so one that is not due loads too
    tables = json.loads(r.stdout)["tables"] if r.stdout else {}
    assert tables, f"no run happened: {r.stderr}"
    return r.returncode, tables


def types(rv, table):
    return rv.target("select column_name, data_type from information_schema.columns "
                     "where table_schema = 'raw_files' and table_name = %s order by ordinal_position", [table])


def test_a_csv_an_excel_and_a_parquet_file_are_mirrored(files):
    code, answer = load(files, '"customers_csv.csv" = { key = ["customer_no"], sep = ";" }\n'
                               '"customers_xlsx.xlsx" = { key = ["customer_no"] }\n'
                               '"customers_parquet.parquet" = { key = ["customer_no"] }\n')
    assert code == 0, answer
    assert {t: a["inserted"] for t, a in answer.items()} == {
        "raw_files.customers_csv": 3, "raw_files.customers_xlsx": 3, "raw_files.customers_parquet": 3}
    as_text = [("1", "Anna", "2.5"), ("2", "Ben", None), ("3", "Cleo", "10.0")]
    assert files.target("select * from raw_files.customers_csv order by 1") == as_text
    assert files.target("select * from raw_files.customers_xlsx order by 1") == as_text
    assert files.target("select * from raw_files.customers_parquet order by 1") == CUSTOMERS
    assert files.target("select distinct driver_version from _rowvioli.runs") == [
        (f"duckdb {importlib.metadata.version('duckdb')}",)]  # story 38


def test_csv_and_excel_arrive_as_text_and_parquet_keeps_its_types(files):
    code, answer = load(files, '"customers_csv.csv" = { sep = ";" }\n"customers_xlsx.xlsx" = {}\n'
                               '"customers_parquet.parquet" = {}\n')
    assert code == 0, answer
    text = [("customer_no", "text"), ("name", "text"), ("balance", "text")]
    assert types(files, "customers_csv") == text
    assert types(files, "customers_xlsx") == text
    assert types(files, "customers_parquet") == [("customer_no", "bigint"), ("name", "text"),
                                                 ("balance", "double precision")]


def test_columns_names_types_for_csv_and_excel(files):
    named = 'columns = { customer_no = "integer", balance = "decimal(10,2)" }'
    code, answer = load(files, f'"customers_csv.csv" = {{ key = ["customer_no"], sep = ";", {named} }}\n'
                               f'"customers_xlsx.xlsx" = {{ key = ["customer_no"], {named} }}\n')
    assert code == 0, answer
    for table in ("customers_csv", "customers_xlsx"):
        assert types(files, table) == [("customer_no", "integer"), ("name", "text"), ("balance", "numeric")]
        # DuckDB's decimal keeps its precision and scale
        assert files.target(f"select format_type(atttypid, atttypmod) from pg_attribute where attname = 'balance'"
                            f" and attrelid = 'raw_files.{table}'::regclass") == [("numeric(10,2)",)]
        assert files.target(f"select customer_no, balance from raw_files.{table} order by 1") == [
            (1, Decimal("2.5")), (2, None), (3, Decimal("10"))]


def test_the_separator_option_is_passed_to_duckdb(files):
    # a wrong separator proves the option is not sniffed away: the whole line becomes one column
    code, answer = load(files, '"customers_csv.csv" = {}\n', options='sep = ","')
    assert code == 0, answer
    assert types(files, "customers_csv") == [("customer_no;name;balance", "text")]


def test_a_missing_file_fails_the_run_with_a_reason(files):
    code, answer = load(files, '"orders.csv" = { key = ["order_no"] }\n')
    assert code == 1
    assert answer["raw_files.orders"]["status"] == "failed"
    assert "orders.csv" in answer["raw_files.orders"]["reason"]
    assert files.target("select status from _rowvioli.status") == [("failed",)]


def test_a_column_type_that_is_not_a_type_name_fails_and_reaches_no_query(files):
    code, answer = load(files, '"customers_csv.csv" = { sep = ";", '
                               'columns ={ name = "text) AS name, 1 AS x --" } }\n')
    assert code == 1
    assert "is not a column type" in answer["raw_files.customers_csv"]["reason"]


def test_two_csv_files_of_a_source_become_two_target_tables_named_after_the_files(files):
    (files.dir / "files" / "Orders.csv").write_text("order_no;customer_no\n7;1\n")
    code, answer = load(files, '"customers_csv.csv" = { key = ["customer_no"], sep = ";" }\n'
                               '"Orders.csv" = { key = ["order_no"], sep = ";" }\n')
    assert code == 0, answer
    assert {t: a["inserted"] for t, a in answer.items()} == {"raw_files.customers_csv": 3, "raw_files.orders": 1}
    assert files.target("select * from raw_files.orders") == [("7", "1")]


def test_a_csv_and_an_excel_file_of_the_same_name_fail_apply_as_one_target_table(files):
    files.definition({"files.toml": f"""
[files]
type = "file"
max_age = "1h"
[files.connection]
path = "{files.dir / 'files'}"
[files.tables]
"customers.csv" = {{}}
"customers.xlsx" = {{}}
"""})
    r = files.run("apply", "sources")
    assert r.returncode == 1
    assert "both become raw_files.customers" in r.stderr


# each way out has a pattern twin: a pattern keeps the promise for every file it matches
@pytest.mark.parametrize("name", ["../outside.csv", "{abs}", "link.csv", "../outsid?.csv", "{abs_pattern}",
                                  "lin?.csv", "*", "away/*.csv"])
def test_a_table_outside_the_connections_path_fails_naming_the_table(files, name):
    outside = files.dir / "outside.csv"
    outside.write_text("a\n1\n")
    (files.dir / "away").mkdir()
    (files.dir / "away" / "far.csv").write_text("a\n1\n")
    (files.dir / "files" / "link.csv").symlink_to(outside)
    (files.dir / "files" / "away").symlink_to(files.dir / "away")
    name = name.format(abs=outside, abs_pattern=str(outside)[:-1] + "?")
    code, answer = load(files, f'"{name}" = {{ key = ["a"], target_table = "x" }}\n')
    assert code == 1
    reason = answer["raw_files.x"]["reason"]
    assert name in reason and "a table must be a file inside" in reason
    assert files.target("select count(*) from information_schema.tables where table_name = 'x'") == [(0,)]


def test_a_name_with_brackets_reads_that_file_and_not_the_one_duckdb_would_match(files):
    (files.dir / "files" / "x[1].csv").write_text("a,b\nbracket,1\n")
    (files.dir / "files" / "x1.csv").write_text("a,b\nplain,1\n")
    code, answer = load(files, '"x[1].csv" = { target_table = "x" }\n')
    assert code == 0, answer
    assert files.target("select * from raw_files.x") == [("bracket", "1")]


def orders(rv, *numbers):
    for n in numbers:
        (rv.dir / "files" / f"orders_{n}.csv").write_text(f"order_no;amount\n{n};{n}0\n")


def test_a_pattern_mirrors_every_matching_file_and_a_new_file_arrives_on_the_next_run(files):
    orders(files, 1, 2)
    code, answer = load(files, '"orders_*.csv" = { key = ["order_no"], sep = ";", target_table = "orders" }\n')
    assert code == 0, answer
    assert files.target("select * from raw_files.orders order by 1") == [("1", "10"), ("2", "20")]
    orders(files, 3)
    r = files.run("run", "files", "orders_*.csv")
    assert json.loads(r.stdout)["tables"]["raw_files.orders"] == {"status": "ok", "inserted": 1, "updated": 0,
                                                                  "deleted": 0}


@pytest.mark.parametrize("kind", ["csv", "jsonl"])
def test_a_pattern_of_a_thousand_files_mirrors_with_few_open_files(files, kind):
    for n in range(1000):  # a file a day for almost three years
        (files.dir / "files" / f"day_{n:04}.{kind}").write_text(
            f"order_no,amount\n{n},{n}0\n" if kind == "csv" else json.dumps({"order_no": n, "amount": n * 10}))
    files.definition({"files.toml": f"""
[files]
type = "file"
max_age = "1h"
[files.connection]
path = "{files.dir / 'files'}"
[files.tables]
"day_*.{kind}" = {{ key = ["order_no"], target_table = "orders" }}
"""})
    assert files.run("apply", "sources").returncode == 0
    # the run's process inherits the limit: a file held open per match would exceed it
    r = files.run("run", timeout=120, open_files=128)
    assert json.loads(r.stdout)["tables"]["raw_files.orders"] == {"status": "ok", "inserted": 1000, "updated": 0,
                                                                  "deleted": 0}, r.stderr


def test_a_pattern_keeps_equal_rows_of_two_files_and_reads_columns_by_name(files):
    (files.dir / "files" / "part_1.csv").write_text("a,b\n1,x\n")
    (files.dir / "files" / "part_2.csv").write_text("a,b\n1,x\n")
    (files.dir / "files" / "part_3.csv").write_text("b,a\ny,2\n")
    code, answer = load(files, '"part_*.csv" = { target_table = "parts" }\n')
    assert code == 0, answer
    assert files.target("select a, b from raw_files.parts order by a") == [("1", "x"), ("1", "x"), ("2", "y")]


def test_a_column_name_with_a_double_quote_arrives_under_that_name(files):
    (files.dir / "files" / "quoted.csv").write_text('id,"a""b"\n1,x\n')
    code, answer = load(files, '"quoted.csv" = { key = ["id"] }\n')
    assert code == 0, answer
    assert files.target("select column_name from information_schema.columns where table_schema = 'raw_files'"
                        " and table_name = 'quoted' order by ordinal_position") == [("id",), ('a"b',)]
    assert files.target('select "a""b" from raw_files.quoted') == [("x",)]


def test_an_empty_csv_fails_saying_it_is_empty(files):
    (files.dir / "files" / "empty.csv").write_text("")
    code, answer = load(files, '"empty.csv" = {}\n')
    assert code == 1
    assert answer["raw_files.empty"]["reason"] == "empty.csv: the file is empty"


def test_a_pattern_that_matches_nothing_fails(files):
    code, answer = load(files, '"orders_*.csv" = { target_table = "orders" }\n')
    assert code == 1
    assert "orders_*.csv: no file in" in answer["raw_files.orders"]["reason"]


def test_files_of_a_pattern_of_different_kinds_fail_naming_them(files):
    orders(files, 1, 2)
    (files.dir / "files" / "orders_3.json").write_text('[{"order_no": 3}]')
    code, answer = load(files, '"orders_*" = { key = ["order_no"], sep = ";", target_table = "orders" }\n')
    assert code == 1
    assert "orders_*: matches .csv and .json files" in answer["raw_files.orders"]["reason"]


def test_F1_F6_files_with_more_or_fewer_columns_load_and_a_column_missing_from_a_file_or_a_run_is_empty(files):
    orders(files, 1, 2)
    d = files.dir / "files"
    (d / "orders_3.csv").write_text("order_no;amount;note\n3;30;n3\n")  # F6: one more column
    code, answer = load(files, '"orders_*.csv" = { key = ["order_no"], sep = ";", target_table = "orders" }\n')
    assert code == 0, answer
    mirror = "select * from raw_files.orders order by 1"
    assert files.target(mirror) == [("1", "10", None), ("2", "20", None), ("3", "30", "n3")]
    (d / "orders_2.csv").write_text("order_no;note\n2;n2\n")  # F1: one file without amount
    assert files.run("run", "files", "orders_*.csv").returncode == 0
    assert files.target(mirror) == [("1", "10", None), ("2", None, "n2"), ("3", "30", "n3")]
    for n in (2, 3):  # F1: no file has note in this run
        (d / f"orders_{n}.csv").write_text(f"order_no;amount\n{n};{n}0\n")
    assert files.run("run", "files", "orders_*.csv").returncode == 0
    assert files.target(mirror) == [("1", "10", None), ("2", "20", None), ("3", "30", None)]
    log_replays(files, "raw_files.orders")


@pytest.mark.parametrize("kind", ["csv", "xlsx", "parquet", "jsonl"])
@pytest.mark.parametrize("table", ["orders_1.{}", "orders_*.{}"])
def test_a_field_named_under_columns_that_the_files_lack_is_empty_in_every_reader(files, kind, table):  # as REST
    for n in (1, 2):
        rows = pa.table({"order_no": [n], "amount": [n * 10]})
        path = files.dir / "files" / f"orders_{n}.{kind}"
        if kind == "parquet":
            pq.write_table(rows, path)
        elif kind == "xlsx":
            db = duckdb.connect()
            db.execute("INSTALL excel; LOAD excel")
            db.register("rows", rows)
            db.execute(f"COPY rows TO '{path}' (FORMAT xlsx, HEADER true)")
        else:
            path.write_text(f"order_no,amount\n{n},{n * 10}\n" if kind == "csv" else json.dumps(rows.to_pylist()[0]))
    named = 'columns = { order_no = "integer", note = "integer", amount = "integer" }'
    code, answer = load(files, f'"{table.format(kind)}" = {{ key = ["order_no"], target_table = "orders", {named} }}\n')
    assert code == 0, answer
    assert types(files, "orders")[-1] == ("note", "integer")
    assert files.target("select order_no, amount, note from raw_files.orders order by 1") == [
        (1, 10, None), (2, 20, None)][:1 if "_1" in table else 2]


def test_a_key_column_named_under_columns_that_no_file_has_stops_the_run_as_null(files):  # as REST
    orders(files, 1, 2)
    code, answer = load(files, '"orders_*.csv" = { key = ["order_id"], sep = ";", target_table = "orders", '
                               'columns = { order_id = "integer" } }\n')
    assert (code, answer["raw_files.orders"]["reason"]) == (1, 'a key column of ("order_id") is null')
    assert files.target("select to_regclass('raw_files.orders')") == [(None,)]


def test_a_column_gone_from_the_files_for_good_leaves_the_mirror_by_hand_and_keeps_its_history(files):  # H2
    orders(files, 1, 2)
    d = files.dir / "files"
    (d / "orders_3.csv").write_text("order_no;amount;note\n3;30;n3\n")
    assert load(files, '"orders_*.csv" = { key = ["order_no"], sep = ";", target_table = "orders" }\n')[0] == 0
    [(before,)] = files.target("select loaded_at from _rowvioli.tables")
    (d / "orders_3.csv").write_text("order_no;amount\n3;30\n")  # note is gone from every file
    assert files.run("run", "files").returncode == 0  # a run empties it
    files.target('ALTER TABLE "raw_files"."orders" DROP COLUMN "note"')  # the way docs/loading.md gives
    assert files.run("run", "files").returncode == 0
    assert files.target("select * from raw_files.orders order by 1") == [("1", "10"), ("2", "20"), ("3", "30")]
    assert files.target("select note from raw_files.orders__history where order_no = '3' and _valid_from <= %s "
                        "and (_valid_to > %s or _valid_to is null)", [before, before]) == [("n3",)]
    assert files.target("select _op, mirror, \"by\" from _rowvioli.columns__history where \"column\" = 'note' "
                        "order by _valid_from") == [("I", True, "found"), ("U", False, "hand")]
    assert files.run("run", "files").returncode == 0  # and it does not come back
    assert files.target("select count(*) from raw_files.orders__log where note is not null") == [(1,)]
    log_replays(files, "raw_files.orders")


@pytest.mark.parametrize("table", ['key = ["order_no"], log = false, ', ""])
def test_without_a_change_log_a_column_missing_from_the_files_stops_and_says_how_to_drop_it(files, table):  # story 8
    orders(files, 1, 2)
    tables = f'"orders_*.csv" = {{ {table}sep = ";", target_table = "orders" }}\n'
    assert load(files, tables)[0] == 0
    for n in (1, 2):
        (files.dir / "files" / f"orders_{n}.csv").write_text(f"order_no\n{n}\n")
    code, answer = load(files, tables)
    assert code == 1
    assert answer["raw_files.orders"]["reason"] == (
        "column amount is missing in the source; without a change log its values are nowhere else, so a person drops "
        'it: ALTER TABLE "raw_files"."orders" DROP COLUMN "amount"')
    assert files.target("select amount from raw_files.orders order by 1") == [("10",), ("20",)]
    files.target('ALTER TABLE "raw_files"."orders" DROP COLUMN "amount"')  # the way out
    assert load(files, tables)[0] == 0
    assert files.target("select * from raw_files.orders order by 1") == [("1",), ("2",)]


def test_a_column_a_person_added_to_the_mirror_of_a_file_is_not_emptied_and_stops_the_run(files):  # story 8, G1
    orders(files, 1, 2)
    code, answer = load(files, '"orders_*.csv" = { key = ["order_no"], sep = ";", target_table = "orders" }\n')
    assert code == 0, answer
    files.target("alter table raw_files.orders add column memo text")
    files.target("update raw_files.orders set memo = 'mine'")
    r = files.run("run", "files", "orders_*.csv")
    assert r.returncode == 1
    assert json.loads(r.stdout)["tables"]["raw_files.orders"]["reason"].startswith(
        "column memo of the mirror is not in the change log")
    assert files.target("select distinct memo from raw_files.orders") == [("mine",)]


def test_a_pattern_without_target_table_fails_apply(files):
    files.definition({"files.toml": f"""
[files]
type = "file"
max_age = "1h"
[files.connection]
path = "{files.dir / 'files'}"
[files.tables]
"orders_*.csv" = {{}}
"""})
    r = files.run("apply", "sources")
    assert r.returncode == 1
    assert "orders_*.csv: a pattern needs target_table" in r.stderr


# DuckDB read the first as one column `id,name`, and the second as the last line alone, its header dropped
@pytest.mark.parametrize("text", ["id,name\n1,Anna\n2,Ben,extra\n3,Cleo\n", "id,name\n1,Anna\n2,Ben,extra\n"])
def test_a_ragged_csv_fails_naming_the_separator_not_a_missing_column(files, text):
    (files.dir / "files" / "ragged.csv").write_text(text)
    code, answer = load(files, '"ragged.csv" = { key = ["id"] }\n')
    assert code == 1
    reason = answer["raw_files.ragged"]["reason"]
    assert "no column id" not in reason and "sep" in reason


NESTED = [{"id": 1, "amount": 2.5, "big": 123456789012345678901234567890, "day": "2024-01-02", "note": None,
           "tags": ["a", "b"], "address": {"city": "Bern", "zip": [3000]}, "mixed": 1, "ok": True},
          {"id": 2, "amount": 3, "big": 1, "day": "2024-02-03", "tags": [], "address": {"city": "Biel"},
           "mixed": "two", "ok": False}]


def test_json_and_json_lines_arrive_as_jsonb_as_written_and_a_second_run_changes_nothing(files):
    (files.dir / "files" / "people.json").write_text(json.dumps(NESTED))
    (files.dir / "files" / "lines.jsonl").write_text("".join(json.dumps(r) + "\n" for r in NESTED))
    code, answer = load(files, '"people.json" = { key = ["id"] }\n"lines.jsonl" = { key = ["id"] }\n')
    assert code == 0, answer
    for table in ("people", "lines"):
        assert {t for _, t in types(files, table)} == {"jsonb"}
        assert files.target(f"select * from raw_files.{table} order by id") == [
            (1, 2.5, 123456789012345678901234567890, "2024-01-02", None, ["a", "b"],
             {"city": "Bern", "zip": [3000]}, 1, True),
            (2, 3, 1, "2024-02-03", None, [], {"city": "Biel"}, "two", False)]
    for table in ("people.json", "lines.jsonl"):
        r = files.run("run", "files", table)
        assert list(json.loads(r.stdout)["tables"].values()) == [
            {"status": "ok", "inserted": 0, "updated": 0, "deleted": 0}], r.stdout


def test_columns_casts_a_json_value_from_its_text(files):
    (files.dir / "files" / "people.json").write_text(json.dumps(NESTED))
    code, answer = load(files, '"people.json" = { key = ["id"], columns = { id = "bigint", day = "date", '
                               'mixed = "text", amount = "decimal(10,2)", big = "hugeint" } }\n')
    assert code == 0, answer
    assert files.target("select id, day, mixed, amount, big from raw_files.people order by id") == [
        (1, date(2024, 1, 2), "1", Decimal("2.50"), 123456789012345678901234567890),
        (2, date(2024, 2, 3), "two", Decimal("3.00"), 1)]


@pytest.mark.parametrize("name, content, table", [
    ("pins.csv", "id;n;d\n1;42;2024-01-01\n2;secret-value;2024-01-02\n", '{ key = ["id"], sep = ";", columns = '
                                                                          '{ d = "date", n = "integer" } }'),
    ("pins.json", '{"id": 1, "n": 42}\n{"id": 2, "n": "secret-value"}\n',
     '{ key = ["id"], columns = { n = "integer" } }'),
])
def test_a_value_a_type_under_columns_does_not_take_names_table_column_and_type_but_not_the_value(
        files, name, content, table):
    (files.dir / "files" / name).write_text(content)
    code, answer = load(files, f'"{name}" = {table}\n')
    assert code == 1
    assert answer["raw_files.pins"]["reason"] == (
        f"{name}: column n is not integer in every row; change the value in the file, or its type under columns")
    r = files.run("run", "files")
    assert "secret-value" not in r.stdout + r.stderr + str(files.target(
        "select reason from _rowvioli.tables union all select reason from _rowvioli.runs"))


def test_a_value_a_type_under_columns_does_not_take_in_a_later_read_of_a_pattern_is_named_the_same(files):
    # among several files of the second read (50 files are read at once), where DuckDB fails only once batches are read
    for i in range(60):
        (files.dir / "files" / f"o_{i:02}.csv").write_text(f"id;n\n{i};{'secret-value' if i == 55 else i}\n")
    code, answer = load(files, '"o_*.csv" = { sep = ";", columns = { n = "integer" }, target_table = "o" }\n')
    assert code == 1
    [(reason,)] = files.target("select reason from _rowvioli.status")
    assert reason == (  # the error crosses Arrow's stream, and the run gives it as the connector raised it
        "o_*.csv: column n is not integer in every row; change the value in the file, or its type under columns")


def test_a_name_with_a_line_break_in_a_reason_that_crosses_arrows_stream_is_not_cut_there(files):
    # ticket 11 left it untried: the file connector's own reason, raised while the driver reads the stream
    for i in range(60):
        (files.dir / "files" / f"o_{i:02}.csv").write_text(f'id;"n\nx"\n{i};{"secret-value" if i == 55 else i}\n')
    code, answer = load(files, '"o_*.csv" = { sep = ";", columns = { "n\\nx" = "integer" }, target_table = "o" }\n')
    assert code == 1
    assert files.target("select reason from _rowvioli.status") == [(
        "o_*.csv: column n?x is not integer in every row; change the value in the file, or its type under columns",)]


def test_a_value_a_reader_option_of_duckdb_does_not_take_is_named_without_the_value(files):
    (files.dir / "files" / "o.csv").write_text("id;n\n1;secret-value\n")
    code, answer = load(files, '"o.csv" = { sep = ";", column_types = { n = "INTEGER" } }\n')
    assert code == 1
    assert files.target("select reason from _rowvioli.status") == [
        ("o.csv: a value in the file does not convert to the type its column is read as",)]


def test_a_json_file_whose_later_rows_differ_from_its_first_arrives_whole(files):
    # beyond the 20480 rows DuckDB looks at first: other types, and a key that was not there before
    rows = [{"id": i, "v": i} for i in range(25000)] + [{"id": 25000, "v": "x", "late": True}]
    (files.dir / "files" / "long.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    code, answer = load(files, '"long.jsonl" = { key = ["id"] }\n')
    assert code == 0, answer
    assert files.target("select v, late from raw_files.long where id = '25000'") == [("x", True)]


@pytest.mark.parametrize("text", ["[1, 2]", "[]"])
def test_a_json_file_that_is_not_a_list_of_objects_fails(files, text):
    (files.dir / "files" / "odd.json").write_text(text)
    code, answer = load(files, '"odd.json" = {}\n')
    assert code == 1
    assert "records" in answer["raw_files.odd"]["reason"]


def test_a_csv_with_only_a_header_is_mirrored_as_an_empty_table(files):
    (files.dir / "files" / "empty.csv").write_text("id;name\n")
    code, answer = load(files, '"empty.csv" = { key = ["id"], sep = ";" }\n')
    assert code == 0, answer
    assert files.target("select count(*) from raw_files.empty") == [(0,)]


def test_a_missing_files_reason_shows_the_directory(files):
    code, answer = load(files, '"gone.csv" = {}\n')
    assert code == 1
    assert [a["reason"] for a in answer.values()] == [f"gone.csv: no such file in {files.dir / 'files'}"]


def test_the_password_of_a_url_in_the_path_is_hidden_but_the_rest_of_it_is_not(files):
    files.definition({"files.toml": """
[files]
type = "file"
max_age = "1h"
[files.connection]
path = "https://anna:hunter2pw@host/dir"
[files.tables]
"gone.csv" = {}
"""})
    assert files.run("apply", "sources").returncode == 0
    r = files.run("run")
    assert "no such file in https://anna:***@host/dir" in r.stdout and "hunter2pw" not in r.stdout


def test_a_nul_byte_in_a_text_value_is_removed_and_a_second_run_changes_nothing(files):
    pq.write_table(pa.table({"id": [1, 2], "name": ["a\x00b", "c"]}), files.dir / "files" / "nul.parquet")
    code, answer = load(files, '"nul.parquet" = { key = ["id"] }\n')
    assert code == 0, answer
    assert files.target("select * from raw_files.nul order by 1") == [(1, "ab"), (2, "c")]
    code, answer = load(files, '"nul.parquet" = { key = ["id"] }\n')
    assert answer["raw_files.nul"] == {"status": "ok", "inserted": 0, "updated": 0, "deleted": 0}


def test_a_csv_header_with_one_name_twice_arrives_with_the_second_numbered(files):  # cases A22, as it is today
    (files.dir / "files" / "twice.csv").write_text("a;a;b\n1;2;3\n")
    code, answer = load(files, '"twice.csv" = {}\n')
    assert code == 0, answer
    assert types(files, "twice") == [("a", "text"), ("a_1", "text"), ("b", "text")]
    assert files.target("select * from raw_files.twice") == [("1", "2", "3")]


@pytest.mark.parametrize("long", ["c" * 64, "ä" * 32])  # bytes, not characters
def test_A20_a_column_name_longer_than_63_bytes_fails_the_run_and_names_the_column(files, long):
    (files.dir / "files" / "long.csv").write_text(f"{'d' * 63};{long}\n1;2\n")
    code, answer = load(files, '"long.csv" = {}\n')
    assert code == 1
    assert answer["raw_files.long"]["reason"] == (
        f"column {long} of the source is longer than 63 bytes, the most Postgres keeps of a name: give it a shorter "
        "name in the source")
    assert files.target("select to_regclass('raw_files.long')") == [(None,)]
    # a name of 63 bytes, also of characters of two bytes, loads whole
    (files.dir / "files" / "long.csv").write_text(f"{'d' * 63};{'ä' * 31}d\n1;2\n")
    code, answer = load(files, '"long.csv" = {}\n')
    assert code == 0, answer
    assert [c for c, _ in types(files, "long")] == ["d" * 63, "ä" * 31 + "d"]


def test_A20_two_names_equal_in_their_first_63_bytes_fail_and_name_both(files):
    (files.dir / "files" / "long.csv").write_text(f"k;{'c' * 63}y;{'c' * 63}z\n0;1;2\n")
    code, answer = load(files, '"long.csv" = {}\n')
    assert code == 1
    assert answer["raw_files.long"]["reason"] == (
        f"columns {'c' * 63}y and {'c' * 63}z of the source are equal in their first 63 bytes, the most Postgres "
        "keeps of a name: give them names in the source that differ there")


def test_a_csv_without_a_header_gets_column0_and_up_and_keeps_its_first_line(files):  # cases F8, as it is today
    (files.dir / "files" / "nohead.csv").write_text("1;Anna\n2;Ben\n")
    code, answer = load(files, '"nohead.csv" = {}\n')
    assert code == 0, answer
    assert types(files, "nohead") == [("column0", "text"), ("column1", "text")]
    assert files.target("select * from raw_files.nohead order by 1") == [("1", "Anna"), ("2", "Ben")]


def test_a_timestamp_finer_than_microseconds_arrives_cut_to_microseconds(files):  # cases B16, as it is today
    pq.write_table(pa.table({"k": [1], "t": pa.array([1767225600123456789], pa.timestamp("ns"))}),
                   files.dir / "files" / "ns.parquet")
    code, answer = load(files, '"ns.parquet" = {}\n')
    assert code == 0, answer
    assert files.target("select t from raw_files.ns") == [(datetime(2026, 1, 1, 0, 0, 0, 123456),)]


def write(rv, name, rows):
    """A JSON or an Excel file of `rows`, dicts of text; a key a row lacks is a field the file lacks."""
    path = rv.dir / "files" / name
    if name.endswith(".json"):
        return path.write_text(json.dumps(rows))
    columns = list(dict.fromkeys(k for r in rows for k in r))
    db = duckdb.connect()
    db.execute("LOAD excel")
    db.register("t", pa.table({c: [r.get(c) for r in rows] for c in columns}))
    db.execute(f"COPY t TO '{path}' (FORMAT xlsx, HEADER true)")


@pytest.mark.parametrize("kind, unpinned", [("xlsx", "text"), ("json", "jsonb")])
def test_excel_and_json_go_through_every_change_of_shape_a_csv_goes_through(files, kind, unpinned):  # ticket 14
    """A pattern whose files differ, a header renamed, a pin set, changed and taken out, a field missing
    (decision 54)."""
    from test_columns_go_and_come import columns
    table = f'"t_*.{kind}" = {{{{ key = ["id"], target_table = "t"{{}} }}}}\n'
    text = "#>> '{}'" if kind == "json" else ""  # a JSON value as its text
    type = "select format_type(atttypid, atttypmod) from pg_attribute where attname = 'amount' and attrelid in " \
           "('raw_files.t'::regclass, 'raw_files.t__log'::regclass)"
    write(files, f"t_1.{kind}", [{"id": "1", "amount": "10", "note": "a"}, {"id": "2", "amount": "20", "note": "b"}])
    write(files, f"t_2.{kind}", [{"id": "3", "amount": "30"}])  # a file without note
    code, answer = load(files, table.format(""))
    assert code == 0, answer
    assert files.target(f"select id {text}, amount {text}, note {text} from raw_files.t order by 1") == [
        ("1", "10", "a"), ("2", "20", "b"), ("3", "30", None)]
    write(files, f"t_1.{kind}", [{"id": "1", "amount": "10", "memo": "a"}, {"id": "2", "amount": "20", "memo": "b"}])
    code, answer = load(files, table.format(', renamed = { memo = "note" }'))  # the header renamed
    assert code == 0, answer
    assert columns(files, "raw_files.t") == ["id", "amount", "memo"]
    for pin, expected in [("integer", "integer"), ("bigint", "integer"), (None, unpinned)]:  # set, widened, taken out
        code, answer = load(files, table.format(f', columns = {{ amount = "{pin}" }}' if pin else ""))
        assert code == 0, answer
        assert files.target(type) == [(expected,), (expected,)], pin
    write(files, f"t_2.{kind}", [{"id": "3", "memo": "c"}])  # a field missing
    code, answer = load(files, table.format(""))
    assert code == 0, answer
    assert files.target(f"select amount {text}, memo {text} from raw_files.t order by id {text}") == [
        ("10", "a"), ("20", "b"), (None, "c")]
    log_replays(files, "raw_files.t")
