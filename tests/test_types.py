"""Types: the target keeps its type while the values fit, is widened when one does not, and a type of another family
is a column that goes and comes (spec tests, stage 3; the numbers are those of `.scratch/schema-changes/cases.md`)."""
from test_columns_go_and_come import log_replays
from test_history import again
from test_run import apply, definition, erp, ok  # noqa: F401 (erp is a fixture)

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
