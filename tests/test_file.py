"""The `file` connector: CSV, Excel, Parquet and JSON files and patterns from a directory (spec test 15)."""
import json
from datetime import date
from decimal import Decimal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

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


@pytest.mark.parametrize("other, says", [("orders_3.json", "orders_*: matches .csv and .json files"),
                                         ("orders_3.csv", "orders_3.csv has the columns order_no VARCHAR, "
                                                          "amount VARCHAR, note VARCHAR")])
def test_files_of_a_pattern_of_different_kinds_or_columns_fail_naming_the_file(files, other, says):
    orders(files, 1, 2)
    (files.dir / "files" / other).write_text('[{"order_no": 3}]' if other.endswith(".json")
                                             else "order_no;amount;note\n3;30;x\n")
    code, answer = load(files, '"orders_*" = { key = ["order_no"], sep = ";", target_table = "orders" }\n')
    assert code == 1
    assert says in answer["raw_files.orders"]["reason"]


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
