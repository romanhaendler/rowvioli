"""Types: the target keeps its type while the values fit, is widened when one does not, and a type of another family
is a column that goes and comes (spec tests, stage 3; the numbers are those of `.scratch/schema-changes/cases.md`)."""
import pytest

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
