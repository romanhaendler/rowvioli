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
    r = rv.run("run")
    assert r.stdout, r.stderr
    return r.returncode, json.loads(r.stdout)["tables"]


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


@pytest.mark.parametrize("name", ["../outside.csv", "{abs}"])
def test_a_table_outside_the_connections_path_fails_naming_the_table(files, name):
    outside = files.dir / "outside.csv"
    outside.write_text("a\n1\n")
    name = name.format(abs=outside)
    code, answer = load(files, f'"{name}" = {{ key = ["a"], target_table = "x" }}\n')
    assert code == 1
    assert name.rsplit("/", 1)[-1] in reason and str(files.dir) not in reason  # a reason holds no absolute path
    assert name in reason
    assert files.target("select count(*) from information_schema.tables where table_name = 'x'") == [(0,)]
