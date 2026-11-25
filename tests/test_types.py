"""Types: the target keeps its type while the values fit, is widened when one does not, and a type of another family
is a column that goes and comes (spec tests, stage 3; the numbers are those of `.scratch/schema-changes/cases.md`)."""
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_checks import failed
from test_columns_go_and_come import log_replays
from test_file import files, load  # noqa: F401 (files is a fixture)
from test_history import MIRROR, again, at
from test_run import apply, definition, erp, ok, rows  # noqa: F401 (erp is a fixture)

TYPES = ("select format_type(atttypid, atttypmod) from pg_attribute where attname = %s and attrelid in "
         "(%s::regclass, (%s || '__log')::regclass) order by attrelid::regclass::text")
RECORD = 'select type, source_type, "by" from _rowvioli.columns where "column" = %s'


def types(rv, column, table="raw_erp.amounts"):
    """The column's type in the mirror and in its change log."""
    return [t for (t,) in rv.target(TYPES, [column, table, table])]


def amounts(rv, type, values):
    rv.source(f"create table amounts (id int primary key, a {type})")
    rv.source(f"insert into amounts values {values}")
    apply(rv, definition(rv, '"public.amounts" = { key = ["id"] }\n'))
    ok(rv)


def test_B1_integer_to_bigint_changes_nothing_while_the_values_fit_and_widens_mirror_and_log_when_one_does_not(erp):
    amounts(erp, "integer", "(1, 10), (2, null)")
    erp.source("alter table amounts alter a type bigint")
    erp.source("update amounts set a = 20 where id = 1")
    again(erp)
    assert types(erp, "a") == ["integer", "integer"]
    assert erp.target(RECORD, ["a"]) == [("integer", "bigint", "source")]
    erp.source("update amounts set a = 3000000000 where id = 2")
    again(erp)
    assert types(erp, "a") == ["bigint", "bigint"]
    assert erp.target("select a from raw_erp.amounts order by id") == [(20,), (3000000000,)]
    assert erp.target("select a from raw_erp.amounts__history where id = 2 order by _valid_from") == [
        (None,), (3000000000,)]
    assert erp.target(RECORD, ["a"]) == [("bigint", "bigint", "source")]
    log_replays(erp, "raw_erp.amounts")


@pytest.mark.parametrize("before, after", [("bigint", "integer"), ("numeric(14,4)", "numeric(12,2)")])
def test_B4_a_source_that_narrows_a_type_changes_nothing_in_the_target_and_the_record_notes_its_type(
        erp, before, after):
    amounts(erp, before, "(1, 12)")
    erp.source(f"alter table amounts alter a type {after}")
    erp.source("update amounts set a = 13")
    again(erp)
    assert types(erp, "a") == [before] * 2
    assert erp.target("select a from raw_erp.amounts") == [(13,)]
    assert erp.target(RECORD, ["a"]) == [(before, after, "source")]
    log_replays(erp, "raw_erp.amounts")


def loaded(rv):
    return rv.target("select loaded_at from _rowvioli.tables where target_table = 'amounts'")[0][0]


def max_run(rv):
    return rv.target("select max(run) from _rowvioli.runs")[0][0]


@pytest.mark.parametrize("before, after, old, new", [
    ("integer", "text", 7, "seven"), ("text", "integer", "7", 7), ("boolean", "integer", True, 1),  # B8
    ("integer", "boolean", 1, True),
    ("timestamp", "timestamptz", "2024-01-01 12:00", "2024-01-01 12:00+00"),  # B6
    ("integer[]", "bigint[]", "{1}", "{2}"),  # B13
])
def test_B6_B8_B13_a_type_of_another_family_goes_and_comes_in_one_run_and_the_log_keeps_the_old_values(
        erp, before, after, old, new):
    amounts(erp, before, f"(1, '{old}'), (2, null), (3, '{old}')")
    first = loaded(erp)
    erp.source(f"alter table amounts alter a type {after} using null")
    erp.source(f"update amounts set a = '{new}' where id = 1")
    again(erp)
    second = loaded(erp)
    run = max_run(erp)
    assert [c for (c,) in erp.target("select attname from pg_attribute where attrelid = 'raw_erp.amounts__log'"
                                     "::regclass and attnum > 0 and not attisdropped")][-2:] == [f"a__{run}", "a"]
    named = dict(erp.target("select %s, format_type(%s::regtype, null) union all "
                            "select %s, format_type(%s::regtype, null)", ["before", before, "after", after]))
    assert types(erp, "a") == [named["after"]] * 2
    # one U for each row with a value on either side; the old values end with it
    assert erp.target(f"select _op, id, a__{run} is null, a is null from raw_erp.amounts__log where _run = {run} "
                      "order by id") == [("U", 1, True, False), ("U", 3, True, True)]
    assert erp.target(f"select a__{run} is null, a is null, _valid_from, _valid_to from raw_erp.amounts__history "
                      "where id = 1 order by _valid_from") == [(False, True, first, second), (True, False, second, None)]
    assert erp.target('select _op, "column", mirror, was from _rowvioli.columns__log where _run = %s '
                      'order by "column"', [run]) == [("U", "a", True, None), ("I", f"a__{run}", False, "a")]
    # story 34: the retired column keeps the type the source delivered it in
    assert erp.target('select "column", type, source_type from _rowvioli.columns where "column" like %s order by 1',
                      ["a%"]) == [("a", named["after"], named["after"]),
                                  (f"a__{run}", named["before"], named["before"])]
    log_replays(erp, "raw_erp.amounts")


@pytest.mark.parametrize("table", ['{ key = ["id"], log = false }', "{}"])
def test_B6_B8_without_a_change_log_a_type_of_another_family_stops_and_says_how_to_drop_the_column(erp, table):
    erp.source("create table amounts (id int primary key, a timestamp)")
    erp.source("insert into amounts values (1, '2024-01-01 12:00')")
    apply(erp, definition(erp, f'"public.amounts" = {table}\n'))
    ok(erp)
    erp.source("alter table amounts alter a type timestamptz")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ("column a has changed its type from timestamp without time zone to timestamp with time "
                           "zone, and no change log keeps its values, so a person drops it and the next "
                           'run adds it anew: ALTER TABLE "raw_erp"."amounts" DROP COLUMN "a"')  # x is the password
    erp.target('ALTER TABLE "raw_erp"."amounts" DROP COLUMN "a"')  # the way out
    again(erp)
    assert erp.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'a' "
                      "and attrelid = 'raw_erp.amounts'::regclass") == [("timestamp with time zone",)]


def test_C7_a_key_column_is_widened_like_any_other_and_a_consumers_foreign_key_keeps_its_type(erp):  # story 21
    amounts(erp, "integer", "(1, 10)")
    erp.target("create table public.orders (amount_id integer references raw_erp.amounts (id))")
    erp.target("insert into public.orders values (1)")
    erp.source("alter table amounts alter id type bigint")
    erp.source("insert into amounts values (3000000000, 30)")
    again(erp)
    assert types(erp, "id") == ["bigint", "bigint"]
    assert erp.target("select id from raw_erp.amounts order by id") == [(1,), (3000000000,)]
    assert erp.target("select format_type(atttypid, atttypmod) from pg_attribute where attname = 'amount_id' "
                      "and attrelid = 'public.orders'::regclass") == [("integer",)]
    log_replays(erp, "raw_erp.amounts")


def test_B19_a_column_empty_in_every_row_that_changes_its_family_writes_no_row(erp):
    amounts(erp, "text", "(1, null), (2, null)")
    erp.source("alter table amounts alter a type integer using null")
    again(erp)
    run = max_run(erp)
    assert types(erp, "a") == ["integer", "integer"]
    assert erp.target(f"select count(*) from raw_erp.amounts__log where _run = {run}") == [(0,)]
    assert f"a__{run}" in [c for (c,) in erp.target("select attname from pg_attribute where attrelid = "
                                                    "'raw_erp.amounts__log'::regclass and not attisdropped")]
    log_replays(erp, "raw_erp.amounts")


def test_a_table_stuck_on_a_changed_type_resolves_with_the_first_run(erp):  # story 45
    amounts(erp, "integer", "(1, 10)")
    erp.source("alter table amounts alter a type text")
    # as a run of the version before left it, failing for a while
    erp.target("update _rowvioli.tables set reason = 'column a has changed its type from integer to text', "
               "attempts = 3, requested_at = now()")
    ok(erp)
    assert erp.target("select status, attempts, reason from _rowvioli.status where target_table = 'raw_erp.amounts'") \
        == [("ok", 0, None)]
    assert types(erp, "a") == ["text", "text"]
    log_replays(erp, "raw_erp.amounts")


@pytest.mark.parametrize("before, wide", [("integer", "bigint"), ("date", "timestamp without time zone"),
                                          ("real", "double precision")])
def test_a_type_of_any_family_widened_by_hand_in_the_mirror_is_followed_in_the_change_log(erp, before, wide):
    amounts(erp, before, "(1, '1')" if before != "date" else "(1, '2024-01-01')")
    erp.target(f"alter table raw_erp.amounts alter a type {wide}")  # by hand, within its family
    again(erp)
    assert types(erp, "a") == [wide, wide]
    assert erp.target(RECORD, ["a"]) == [(wide, before, "hand")]
    log_replays(erp, "raw_erp.amounts")


@pytest.mark.parametrize("source, values", [("integer", [(1, 10), (2, None)]), ("text", [(1, "10"), (2, None)])])
def test_G4_a_type_changed_by_hand_to_another_family_stops_and_says_the_way_out_which_works(erp, source, values):
    amounts(erp, "integer", "(1, 10), (2, null)")  # story 47; the source changing too is ticket 17, M4
    erp.target("alter table raw_erp.amounts alter a type text")
    erp.source(f"alter table amounts alter a type {source}")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        "column a of the mirror has the type text, of another family than the integer it has in the change log, and a "
        "run does not change it back; drop it from the mirror and the next run brings it again: "
        'ALTER TABLE "raw_erp"."amounts" DROP COLUMN "a"')
    erp.target('ALTER TABLE "raw_erp"."amounts" DROP COLUMN "a"')
    again(erp)
    assert types(erp, "a") == [source, source]
    assert erp.target("select id, a from raw_erp.amounts order by id") == values
    log_replays(erp, "raw_erp.amounts")


def test_G1_a_column_a_person_added_whose_name_the_source_brings_in_another_family_is_not_one_to_drop(erp):
    amounts(erp, "integer", "(1, 10)")  # story 8: its values are nowhere else, so no next run brings them again
    erp.target("alter table raw_erp.amounts add column memo text")
    erp.target("update raw_erp.amounts set memo = 'mine'")
    erp.source("alter table amounts add column memo integer")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        "column memo of the mirror is not in the change log, so it is not known to be from the source; the source "
        "brings a column memo, which a run would write into: drop it from the mirror, after copying its values into "
        'a table of your own if they are to be kept: CREATE TABLE <a table of yours> AS SELECT "id", "memo" FROM '
        '"raw_erp"."amounts"; ALTER TABLE "raw_erp"."amounts" DROP COLUMN "memo"')
    assert erp.target("select memo from raw_erp.amounts") == [("mine",)]


def test_G1_a_column_a_person_added_whose_name_the_source_brings_in_its_family_is_never_written(erp):  # story 8
    amounts(erp, "integer", "(1, 10)")
    erp.target("alter table raw_erp.amounts add column memo text")
    erp.target("update raw_erp.amounts set memo = 'mine'")
    erp.source("alter table amounts add column memo text")
    erp.source("update amounts set memo = 'theirs'")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == (
        "column memo of the mirror is not in the change log, so it is not known to be from the source; the source "
        "brings a column memo, which a run would write into: drop it from the mirror, after copying its values into "
        'a table of your own if they are to be kept: CREATE TABLE <a table of yours> AS SELECT "id", "memo" FROM '
        '"raw_erp"."amounts"; ALTER TABLE "raw_erp"."amounts" DROP COLUMN "memo"')
    assert erp.target("select memo from raw_erp.amounts") == [("mine",)]
    # the way out as the reason says it: the person's values kept in a table of their own, the source's come
    erp.target('CREATE TABLE public.my_memos AS SELECT "id", "memo" FROM "raw_erp"."amounts"; '
               'ALTER TABLE "raw_erp"."amounts" DROP COLUMN "memo"')
    again(erp)
    assert erp.target("select memo from raw_erp.amounts") == [("theirs",)]
    assert erp.target("select id, memo from public.my_memos") == [(1, "mine")]
    log_replays(erp, "raw_erp.amounts")


def test_a_run_ended_after_max_seconds_while_it_widened_says_so_and_names_the_column(erp):  # story 16
    erp.source("create table amounts (id int primary key, a integer)")
    erp.source("insert into amounts values (1, 1)")
    apply(erp, definition(erp, '"public.amounts" = { key = ["id"], max_seconds = 2 }\n'))
    ok(erp)
    # a consumer's index whose function waits as long as public.pause says: not while it is built, longer than
    # max_seconds once the widening rebuilds it
    erp.target("create table public.pause (seconds float); insert into public.pause values (0)")
    erp.target("create function public.slow(v numeric) returns numeric immutable language plpgsql "
               "as $$ begin perform pg_sleep(seconds) from public.pause; return v; end $$")
    erp.target("create index on raw_erp.amounts (public.slow(a))")
    erp.target("update public.pause set seconds = 3")
    erp.source("alter table amounts alter a type bigint")
    erp.source("update amounts set a = 3000000000 where id = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == ('ended after max_seconds = 2 while widening "raw_erp"."amounts", column a to bigint; raise '
                           "max_seconds once, until a run has widened it")
    assert types(erp, "a") == ["integer", "integer"]


def parquet(rv, values, type):
    pq.write_table(pa.table({"id": pa.array([1, 2], pa.int32()), "n": pa.array(values, type)}),
                   rv.dir / "files" / "counts.parquet")


COUNTS = '"counts.parquet" = { key = ["id"] }\n'


def test_F4_a_guessed_type_that_flips_to_another_family_stops_with_the_hint_to_pin_it(files):
    parquet(files, [42, 43], pa.int64())
    assert load(files, COUNTS)[0] == 0
    parquet(files, ["42", "N/A"], pa.string())
    code, answer = load(files, COUNTS)
    assert code == 1
    assert answer["raw_files.counts"]["reason"] == (
        "column n has changed its type from bigint to text; a source without a catalog guesses its types, so pin it "
        "under columns in the table's definition; where its pin was taken out, a person drops it and the next run adds "
        'it anew: ALTER TABLE "raw_files"."counts" DROP COLUMN "n"')
    assert files.target("select n from raw_files.counts order by id") == [(42,), (43,)]


def test_a_parquet_key_column_that_flips_to_another_family_stops_with_the_way_out_of_a_key(files):  # ticket 15, D1
    pq.write_table(pa.table({"id": pa.array([1, 2], pa.int32())}), files.dir / "files" / "counts.parquet")
    assert load(files, COUNTS)[0] == 0
    pq.write_table(pa.table({"id": pa.array(["1", "2"], pa.string())}), files.dir / "files" / "counts.parquet")
    code, answer = load(files, COUNTS)  # the drop of the generic way out would take the key column for good
    assert answer["raw_files.counts"]["reason"] == (
        "column id has changed its type from integer to text, a type of another family in the key, so a row before "
        "cannot be told from one after: give the table another target_table, which begins a new mirror")


def test_F4_a_parquet_column_that_flips_to_json_stops_with_the_hint_to_pin_it_as_well(files):
    parquet(files, [42, 43], pa.int64())
    assert load(files, COUNTS)[0] == 0
    parquet(files, ["42", '{"n": 43}'], pa.json_())  # Parquet's JSON, a type the file brings itself too
    code, answer = load(files, COUNTS)
    assert code == 1
    assert answer["raw_files.counts"]["reason"].startswith(
        "column n has changed its type from bigint to jsonb; a source without a catalog guesses its types, so pin it "
        "under columns"), answer
    assert files.target("select n from raw_files.counts order by id") == [(42,), (43,)]


def test_F4_a_pin_taken_out_of_a_parquet_column_stops_and_the_drop_it_names_brings_the_file_s_type(files):
    # Parquet's own types can flip, so the run cannot tell a pin taken out; the drop is the way to the file's type
    parquet(files, [42, 43], pa.int64())
    assert load(files, '"counts.parquet" = { key = ["id"], columns = { n = "varchar" } }\n')[0] == 0
    code, answer = load(files, COUNTS)
    assert code == 1
    assert answer["raw_files.counts"]["reason"].endswith('ALTER TABLE "raw_files"."counts" DROP COLUMN "n"')
    files.target('ALTER TABLE "raw_files"."counts" DROP COLUMN "n"')
    assert load(files, COUNTS)[0] == 0
    assert types(files, "n", "raw_files.counts") == ["bigint", "bigint"]
    run = max_run(files)
    assert files.target(f"select n__{run} from raw_files.counts__log where _run < {run} order by id") == [
        ("42",), ("43",)]
    log_replays(files, "raw_files.counts")


def test_a_pin_taken_out_of_a_csv_column_read_by_a_pattern_without_an_extension_goes_back_to_text(files):
    (files.dir / "files" / "counts_1.csv").write_text("id;n\n1;42\n2;7\n")
    table = '"counts_*" = {{ key = ["id"], sep = ";", target_table = "counts"{} }}\n'
    assert load(files, table.format(', columns = { n = "integer" }'))[0] == 0
    code, answer = load(files, table.format(""))
    assert code == 0, answer
    assert types(files, "n", "raw_files.counts") == ["text", "text"]
    assert files.target(RECORD, ["n"]) == [("text", "text", "definition")]
    log_replays(files, "raw_files.counts")


def test_F5_a_guessed_type_that_widens_within_its_family_widens_the_target(files):
    parquet(files, [42, 43], pa.int32())
    assert load(files, COUNTS)[0] == 0
    parquet(files, [42, 3000000000], pa.int64())
    assert load(files, COUNTS)[0] == 0
    assert types(files, "n", "raw_files.counts") == ["bigint", "bigint"]
    assert files.target("select n from raw_files.counts order by id") == [(42,), (3000000000,)]
    log_replays(files, "raw_files.counts")


def test_B11_a_cast_under_columns_that_changes_goes_by_the_same_rules_and_is_recorded_as_by_definition(files):
    (files.dir / "files" / "counts.csv").write_text("id;n\n1;42\n2;3000000000\n")
    table = '"counts.csv" = {{ key = ["id"], sep = ";", columns = {{ n = "{}" }} }}\n'
    code, answer = load(files, table.format("decimal(12,0)"))
    assert code == 0, answer
    code, answer = load(files, table.format("decimal(14,2)"))  # the values fit: nothing to widen
    assert code == 0, answer
    (files.dir / "files" / "counts.csv").write_text("id;n\n1;42.5\n2;3000000000\n")
    assert load(files, table.format("decimal(14,2)"))[0] == 0
    assert types(files, "n", "raw_files.counts") == ["numeric(14,2)", "numeric(14,2)"]
    assert files.target(RECORD, ["n"]) == [("numeric(14,2)", "numeric(14,2)", "definition")]
    log_replays(files, "raw_files.counts")


def test_B11_a_first_type_under_columns_for_a_csv_column_loaded_as_text_goes_and_comes_by_definition(files):
    (files.dir / "files" / "counts.csv").write_text("id;n\n1;42\n2;\n3;7\n")
    table = '"counts.csv" = {{ key = ["id"], sep = ";"{} }}\n'
    assert load(files, table.format(""))[0] == 0
    code, answer = load(files, table.format(', columns = { n = "integer" }'))
    assert code == 0, answer
    run = max_run(files)
    assert types(files, "n", "raw_files.counts") == ["integer", "integer"]
    # a U for each row with a value; the old values end with it and stay in the log under n__<run>
    assert files.target(f"select id, n__{run}, n from raw_files.counts__log where _run = {run} order by id") == [
        ("1", None, 42), ("3", None, 7)]
    assert files.target(f"select n__{run} from raw_files.counts__history where id = '1' order by _valid_from") == [
        ("42",), (None,)]
    assert files.target('select _op, "column", mirror, was, "by" from _rowvioli.columns__log where _run = %s '
                        'order by "column"', [run]) == [("U", "n", True, None, "definition"),
                                                       ("I", f"n__{run}", False, "n", "definition")]
    log_replays(files, "raw_files.counts")


@pytest.mark.parametrize("file, content, back, old", [
    ("counts.csv", "id;n\n1;42\n2;\n3;7\n", "text", "42"),
    ("counts.json", '{"id": "1", "n": 42}\n{"id": "2"}\n{"id": "3", "n": 7}\n', "jsonb", "42")])
def test_B11_a_pin_taken_out_of_columns_goes_and_comes_back_to_what_the_file_brings_by_definition(
        files, file, content, back, old):
    (files.dir / "files" / file).write_text(content)
    table = f'"{file}" = {{{{ key = ["id"], sep = ";"{{}} }}}}\n' if file.endswith(".csv") else \
        f'"{file}" = {{{{ key = ["id"]{{}} }}}}\n'
    code, answer = load(files, table.format(', columns = { n = "integer" }'))
    assert code == 0, answer
    code, answer = load(files, table.format(""))
    assert code == 0, answer
    run = max_run(files)
    assert types(files, "n", "raw_files.counts") == [back, back]
    assert files.target(f"select id, n__{run}, n::text from raw_files.counts__log where _run = {run} order by id") == [
        ("1", None, old), ("3", None, "7")]
    assert files.target('select _op, "column", mirror, was, "by" from _rowvioli.columns__log where _run = %s '
                        'order by "column"', [run]) == [("U", "n", True, None, "definition"),
                                                       ("I", f"n__{run}", False, "n", "definition")]
    log_replays(files, "raw_files.counts")


def test_without_a_change_log_a_pin_taken_out_of_columns_stops_and_says_how_to_drop_it(files):
    (files.dir / "files" / "counts.csv").write_text("id;n\n1;42\n")
    table = '"counts.csv" = {{ key = ["id"], log = false, sep = ";"{} }}\n'
    assert load(files, table.format(', columns = { n = "integer" }'))[0] == 0
    code, answer = load(files, table.format(""))
    assert code == 1
    assert answer["raw_files.counts"]["reason"] == (
        "column n has changed its type from integer to text, and no change log keeps its values, so a "
        'person drops it and the next run adds it anew: ALTER TABLE "raw_files"."counts" DROP COLUMN "n"')


def test_without_a_change_log_a_type_under_columns_of_another_family_stops_and_says_how_to_drop_it(files):
    (files.dir / "files" / "counts.csv").write_text("id;n\n1;42\n")
    table = '"counts.csv" = {{ key = ["id"], log = false, sep = ";"{} }}\n'
    assert load(files, table.format(""))[0] == 0
    code, answer = load(files, table.format(', columns = { n = "integer" }'))
    assert code == 1
    assert answer["raw_files.counts"]["reason"] == (
        "column n has changed its type from text to integer, and no change log keeps its values, so a "
        'person drops it and the next run adds it anew: ALTER TABLE "raw_files"."counts" DROP COLUMN "n"')


def test_a_retired_or_gone_column_keeps_in_the_record_the_type_the_source_last_delivered(erp):  # story 34
    erp.source("create table amounts (id int primary key, a bigint, b bigint)")
    erp.source("insert into amounts values (1, 12, 13)")
    apply(erp, definition(erp, '"public.amounts" = { key = ["id"] }\n'))
    ok(erp)
    erp.source("alter table amounts alter a type integer, alter b type integer")  # narrowed: the target keeps bigint
    again(erp)
    erp.source("alter table amounts alter a type text, drop column b")
    again(erp)
    assert erp.target('select "column", type, source_type, mirror from _rowvioli.columns where "column" <> %s '
                      "order by 1", ["id"]) == [("a", "text", "text", True),
                                                (f"a__{max_run(erp)}", "bigint", "integer", False),
                                                ("b", "bigint", "integer", False)]
    log_replays(erp, "raw_erp.amounts")


FILE = "select relfilenode from pg_class where oid = 'raw_erp.amounts'::regclass"


@pytest.mark.parametrize("before, after, kept, value, widened, rewritten", [
    ("numeric(12,2)", "numeric(14,2)", "1.50", "123456789012.5", "numeric(14,2)", False),  # B2
    ("numeric(12,2)", "numeric(12,4)", "1.50", "1.2345", "numeric(14,4)", True),  # B3: 10 before the point, 4 after
    ("integer", "numeric(12,2)", "1", "1.5", "numeric(12,2)", True),  # B5: an integer counts as 10 digits
    ("date", "timestamp", "2024-01-01", "2024-01-01 12:30", "timestamp without time zone", True),  # B7
    ("real", "double precision", "0.5", "0.1", "double precision", True),
])
def test_B2_B3_B5_B7_a_type_of_the_same_family_is_kept_while_the_values_fit_and_widened_to_hold_both(
        erp, before, after, kept, value, widened, rewritten):
    amounts(erp, before, f"(1, '{kept}')")
    erp.source(f"alter table amounts alter a type {after}")
    file = erp.target(FILE)
    again(erp)
    assert types(erp, "a") == [before] * 2
    erp.source(f"update amounts set a = '{value}'")
    again(erp)
    assert types(erp, "a") == [widened] * 2
    assert erp.target("select a::text from raw_erp.amounts") == erp.source("select a::text from amounts")
    assert (erp.target(FILE) != file) == rewritten  # more digits before the point alone rewrite nothing
    log_replays(erp, "raw_erp.amounts")


ANOTHER_KEY = '"public.customers" = { key = ["customer_no", "name"] }\n'


def test_C7_a_key_column_widened_in_the_run_that_changes_the_key_keeps_the_history(erp):
    ok(erp)
    before = erp.target("select loaded_at from _rowvioli.tables")[0][0], rows(erp.target, MIRROR)
    apply(erp, definition(erp, ANOTHER_KEY))
    erp.source("alter table customers alter customer_no type bigint")
    erp.source("insert into customers values (3000000000, 'Dora', 'Ulm')")
    after = again(erp), rows(erp.source, "select customer_no, name, city from customers")
    assert types(erp, "customer_no", "raw_erp.customers") == ["bigint", "bigint"]
    assert rows(erp.target, MIRROR) == after[1]
    for moment, mirror in (before, after):
        assert at(erp, moment) == mirror, moment
    log_replays(erp)


def test_a_column_of_another_family_in_the_run_that_changes_the_key_keeps_its_old_values_in_the_log(erp):
    ok(erp)
    first = erp.target("select loaded_at from _rowvioli.tables")[0][0]
    old = rows(erp.target, MIRROR)
    apply(erp, definition(erp, ANOTHER_KEY))
    erp.source("alter table customers alter city type integer using length(city)")
    seam = again(erp)
    run = max_run(erp)
    then = f"select customer_no, name, city__{run} from raw_erp.customers__history where _valid_from <= %s and " \
           "(_valid_to > %s or _valid_to is null)"
    assert rows(lambda q: erp.target(q, [first, first]), then) == old
    assert rows(lambda q: erp.target(q, [seam, seam]), "select customer_no, name, city from raw_erp.customers__history"
                " where _valid_from <= %s and (_valid_to > %s or _valid_to is null)") \
        == rows(erp.source, "select customer_no, name, city from customers")
    assert types(erp, "city", "raw_erp.customers") == ["integer", "integer"]
    # the D of every old row carries its old value under the retired name, the I of every new one the new value
    log = f"select _op, customer_no, city__{run}, city from raw_erp.customers__log where _run = {run}"
    assert rows(erp.target, log) == sorted([("D", n, c, None) for n, _, c in old]
                                           + [("I", n, None, c and len(c)) for n, _, c in old], key=repr)
    log_replays(erp)


def slow_index(rv, table, column):
    """A consumer's index on `table` whose function waits as long as public.pause says, per row it indexes."""
    rv.target("create table if not exists public.pause (seconds float); insert into public.pause values (0)")
    rv.target("create or replace function public.slow(v anyelement) returns anyelement immutable language plpgsql "
              "as $$ begin perform pg_sleep(seconds) from public.pause; return v; end $$")
    rv.target(f"create index on {table} (public.slow({column}))")


@pytest.mark.parametrize("change, step", [
    ("alter table customers drop column city",
     'writing a row of the change log for every row of raw_erp.customers that had a value in city; raise max_seconds '
     "once, until a run has written them"),
    ("key", 'replacing raw_erp.customers under the key (customer_no, name), with a D and an I in the change log for '
            "every row; raise max_seconds once, until a run has replaced it"),
    ("alter table customers rename city to town",
     "comparing city with town in every row of raw_erp.customers to prove a rename; raise max_seconds once, until a "
     "run has proven it")])
def test_a_run_ended_after_max_seconds_in_a_long_step_of_a_change_says_which_rolls_back_and_the_next_finishes(
        erp, change, step):  # decision 54, ticket 14 of schema changes
    erp.source("insert into customers select g, 'n' || g, 'c' || (g % 7) from generate_series(4, 30) g")
    table = '"public.customers" = {{ key = [{}], max_seconds = {} }}\n'
    apply(erp, definition(erp, table.format('"customer_no"', 3)))
    ok(erp)
    before = rows(erp.target, MIRROR), rows(erp.target, "select * from raw_erp.customers__log")
    holder = None
    if change == "key":  # the mirror's rows are written anew
        slow_index(erp, "raw_erp.customers", "customer_no")
        apply(erp, definition(erp, table.format('"customer_no", "name"', 3)))
    elif "drop" in change:  # the change log gets a row per row
        slow_index(erp, "raw_erp.customers__log", "customer_no")
    else:  # the proof reads every row of the mirror, which a consumer holds meanwhile
        holder = psycopg.connect(erp.target_url)
        holder.execute("lock table raw_erp.customers in access exclusive mode")
    if holder is None:
        erp.target("update public.pause set seconds = 0.3")  # 9 s for the 30 rows
    if change != "key":
        erp.source(change)
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    if holder:
        holder.close()
    assert reason == f"ended after max_seconds = 3 while {step}"
    assert (rows(erp.target, MIRROR), rows(erp.target, "select * from raw_erp.customers__log")) == before
    if holder is None:  # the next run's rows go through the index at once
        erp.target("update public.pause set seconds = 0")
    apply(erp, definition(erp, table.format('"customer_no", "name"' if change == "key" else '"customer_no"', 30)))
    again(erp)
    log_replays(erp)


def test_a_short_step_after_a_long_one_that_a_consumer_holds_up_names_no_step(erp):
    """The long step said its end, so a short step after it that a consumer holds up is not blamed on it: the run
    does not wait for it while it holds the mirror, and after ten seconds of tries it says what was in use (ticket 15)."""
    erp.source("insert into customers select g, 'n' || g, 'c' || (g % 7) from generate_series(4, 30) g")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_seconds = 30 }\n'))
    ok(erp)
    erp.source("alter table customers drop column city")  # a row of the change log per row: a long step
    erp.target("update _rowvioli.tables set requested_at = now()")
    holder = psycopg.connect(erp.target_url)
    try:  # the record of the columns, after the rows, waits for it; reading it does not
        holder.execute("lock table _rowvioli.columns__log in exclusive mode")
        reason = failed(erp)
    finally:
        holder.close()
    assert reason.startswith("raw_erp.customers, its change log and its history view were held by this run when an "
                             "object it needed was in use"), reason
    again(erp)
    log_replays(erp)
