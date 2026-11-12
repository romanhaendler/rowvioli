"""The `file` connector: CSV, Excel and Parquet files from a directory (spec test 15)."""
import json
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
    (d / "customers.csv").write_text("customer_no;name;balance\n1;Anna;2.5\n2;Ben;\n3;Cleo;10.0\n")
    table = pa.table({"customer_no": [r[0] for r in CUSTOMERS], "name": [r[1] for r in CUSTOMERS],
                      "balance": [r[2] for r in CUSTOMERS]})
    pq.write_table(table, d / "customers.parquet")
    db = duckdb.connect()
    db.execute("INSTALL excel; LOAD excel")
    db.register("customers", table)
    db.execute(f"COPY customers TO '{d / 'customers.xlsx'}' (FORMAT xlsx, HEADER true)")
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
    r = rv.run("run")
    assert r.stdout, r.stderr
    return r.returncode, json.loads(r.stdout)["tables"]


def types(rv, table):
    return rv.target("select column_name, data_type from information_schema.columns "
                     "where table_schema = 'raw_files' and table_name = %s order by ordinal_position", [table])


def test_a_csv_an_excel_and_a_parquet_file_are_mirrored(files):
    code, answer = load(files, '"customers.csv" = { key = ["customer_no"], sep = ";" }\n'
                               '"customers.xlsx" = { key = ["customer_no"] }\n'
                               '"customers.parquet" = { key = ["customer_no"] }\n')
    assert code == 0, answer
    assert {t: a["inserted"] for t, a in answer.items()} == {"raw_files.csv": 3, "raw_files.xlsx": 3,
                                                             "raw_files.parquet": 3}
    as_text = [("1", "Anna", "2.5"), ("2", "Ben", None), ("3", "Cleo", "10.0")]
    assert files.target("select * from raw_files.csv order by 1") == as_text
    assert files.target("select * from raw_files.xlsx order by 1") == as_text
    assert files.target("select * from raw_files.parquet order by 1") == CUSTOMERS


def test_csv_and_excel_arrive_as_text_and_parquet_keeps_its_types(files):
    code, answer = load(files, '"customers.csv" = { sep = ";" }\n"customers.xlsx" = {}\n"customers.parquet" = {}\n')
    assert code == 0, answer
    text = [("customer_no", "text"), ("name", "text"), ("balance", "text")]
    assert types(files, "csv") == text
    assert types(files, "xlsx") == text
    assert types(files, "parquet") == [("customer_no", "bigint"), ("name", "text"),
                                       ("balance", "double precision")]


def test_columns_names_types_for_csv_and_excel(files):
    named = 'columns = { customer_no = "integer", balance = "decimal(10,2)" }'
    code, answer = load(files, f'"customers.csv" = {{ key = ["customer_no"], sep = ";", {named} }}\n'
                               f'"customers.xlsx" = {{ key = ["customer_no"], {named} }}\n')
    assert code == 0, answer
    for table in ("csv", "xlsx"):
        assert types(files, table) == [("customer_no", "integer"), ("name", "text"), ("balance", "numeric")]
        assert files.target(f"select customer_no, balance from raw_files.{table} order by 1") == [
            (1, Decimal("2.5")), (2, None), (3, Decimal("10"))]


def test_the_separator_option_is_passed_to_duckdb(files):
    # a wrong separator proves the option is not sniffed away: the whole line becomes one column
    code, answer = load(files, '"customers.csv" = {}\n', options='sep = ","')
    assert code == 0, answer
    assert types(files, "csv") == [("customer_no;name;balance", "text")]


def test_a_missing_file_fails_the_run_with_a_reason(files):
    code, answer = load(files, '"orders.csv" = { key = ["order_no"] }\n')
    assert code == 1
    assert answer["raw_files.csv"]["status"] == "failed"
    assert "orders.csv" in answer["raw_files.csv"]["reason"]
    assert files.target("select status from _rowvioli.status") == [("failed",)]


def test_a_column_type_that_is_not_a_type_name_fails_and_reaches_no_query(files):
    code, answer = load(files, '"customers.csv" = { sep = ";", columns = { name = "text) AS name, 1 AS x --" } }\n')
    assert code == 1
    assert "is not a column type" in answer["raw_files.csv"]["reason"]
