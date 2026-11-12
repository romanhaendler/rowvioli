"""`rowvioli apply`: the definition written into the target (spec tests 1-4, 18 first part, 20)."""
import shutil
import zoneinfo
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ERP = """
[erp]
type = "postgres"
max_age = "1h"
parallel = 4

[erp.connection]
url = "postgresql://reader:$ERP_PASSWORD@nowhere.invalid:1/erp"

[erp.tables]
"dbo.Customers" = { key = ["customer_no"] }
"dbo.Orders"    = { key = ["order_no"], max_age = "5m" }
"dbo.Notes"     = {}
"""
ENV = {"ERP_PASSWORD": "s3cret-pw"}


@pytest.fixture
def ready(rv):
    assert rv.run("init").returncode == 0
    assert rv.run("key", "new").returncode == 0
    return rv


def apply(rv, files, env=ENV):
    rv.definition(files)
    return rv.run("apply", "sources", env=env)


def tables(rv):
    return rv.target("""select t.id, t.source, source_table, target_table, key, max_age, log, max_delete_share,
                               max_seconds, options, t.enabled, loaded_at, attempted_at, attempts, requested_at, reason
                          from _rowvioli.tables t order by source_table""")


def test_apply_writes_sources_and_tables_and_new_tables_are_due_at_once(ready):
    r = apply(ready, {"erp.toml": ERP})
    assert r.returncode == 0, r.stderr
    assert ready.target("select name, type, target_schema, parallel, enabled from _rowvioli.sources") == [
        ("erp", "postgres", "raw_erp", 4, True)]
    assert ready.target("select s.source_table, s.target_table, t.key, s.max_age, s.status, s.due_at <= now() "
                        "from _rowvioli.status s join _rowvioli.tables t using (id) order by 1") == [
        ("dbo.Customers", "raw_erp.customers", ["customer_no"], timedelta(hours=1), "new", True),
        ("dbo.Notes", "raw_erp.notes", None, timedelta(hours=1), "new", True),
        ("dbo.Orders", "raw_erp.orders", ["order_no"], timedelta(minutes=5), "new", True)]


def test_apply_twice_gives_the_same_rows_and_keeps_what_the_workers_experienced(ready):
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    ready.target("""update _rowvioli.tables set loaded_at = '2026-01-01 00:00Z', attempted_at = '2026-01-01 00:05Z',
                           attempts = 2, requested_at = '2026-01-01 00:06Z', reason = 'zero rows'""")
    sources = "select id, name, type, target_schema, parallel, options, key_id, enabled from _rowvioli.sources"
    before = tables(ready), ready.target(sources)
    r = apply(ready, {"erp.toml": ERP})
    assert r.returncode == 0, r.stderr
    assert (tables(ready), ready.target(sources)) == before


def everything(rv):
    return tables(rv), rv.target("select * from _rowvioli.sources order by id")


def test_apply_with_a_missing_variable_fails_and_changes_nothing(ready):
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    before = everything(ready)
    changed = ERP.replace('max_age = "1h"', 'max_age = "2h"') + '"dbo.Items" = { key = ["item_no"] }\n'
    r = apply(ready, {"erp.toml": changed, "crm.toml": CRM}, env={})
    assert r.returncode != 0 and "ERP_PASSWORD" in r.stderr
    assert everything(ready) == before


CRM = """
[crm]
type = "postgres"
max_age = "1d"
[crm.connection]
url = "postgresql://crm@nowhere.invalid/crm"
[crm.tables]
"public.contacts" = { key = ["id"] }
"""


def test_apply_fills_a_placeholder_nested_in_the_connection(ready):
    nested = ERP.replace('1/erp"', '1/erp"\nssl = { cert = ["$ERP_CERT"] }')
    r = apply(ready, {"erp.toml": nested})
    assert r.returncode != 0 and "ERP_CERT" in r.stderr
    assert apply(ready, {"erp.toml": nested}, env={**ENV, "ERP_CERT": "c"}).returncode == 0


def test_apply_fails_when_two_tables_of_a_source_get_the_same_target_table(ready):
    twice = ERP + '"sales.CUSTOMERS" = { key = ["id"] }\n'
    r = apply(ready, {"erp.toml": twice})
    assert r.returncode != 0
    assert "customers" in r.stderr.lower()
    assert ready.target("select count(*) from _rowvioli.tables") == [(0,)]


def test_a_removed_table_is_disabled_and_nothing_is_deleted(ready):
    assert apply(ready, {"erp.toml": ERP, "crm.toml": CRM}).returncode == 0
    ready.target("create schema raw_erp; create table raw_erp.notes (x int); insert into raw_erp.notes values (1)")
    (ready.dir / "sources" / "crm.toml").unlink()
    r = apply(ready, {"erp.toml": ERP.replace('"dbo.Notes"     = {}', "")})
    assert r.returncode == 0, r.stderr
    assert ready.target("select source_table, enabled from _rowvioli.tables order by 1") == [
        ("dbo.Customers", True), ("dbo.Notes", False), ("dbo.Orders", True), ("public.contacts", False)]
    assert ready.target("select name, enabled from _rowvioli.sources order by 1") == [("crm", False), ("erp", True)]
    assert ready.target("select source_table from _rowvioli.status order by 1") == [("dbo.Customers",), ("dbo.Orders",)]
    assert ready.target("select * from raw_erp.notes") == [(1,)]


def test_a_table_that_comes_back_is_enabled_again_and_keeps_its_id(ready):
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    id = ready.target("select id from _rowvioli.tables where source_table = 'dbo.Notes'")
    assert apply(ready, {"erp.toml": ERP.replace('"dbo.Notes"     = {}', "")}).returncode == 0
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    assert ready.target("select id from _rowvioli.status where source_table = 'dbo.Notes'") == id


def test_a_shortened_max_age_changes_due_at_without_a_run(ready):
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    ready.target("update _rowvioli.tables set loaded_at = '2026-01-01 00:00Z', attempted_at = '2026-01-01 00:00Z'")
    due = "select due_at - loaded_at from _rowvioli.status where source_table = 'dbo.Customers'"
    assert ready.target(due) == [(timedelta(hours=1),)]
    assert apply(ready, {"erp.toml": ERP.replace('max_age = "1h"', 'max_age = "10s"')}).returncode == 0
    assert ready.target(due) == [(timedelta(seconds=10),)]


def test_the_stored_connection_and_the_output_do_not_contain_the_password(ready):
    r = apply(ready, {"erp.toml": ERP})
    assert r.returncode == 0, r.stderr
    [(blob,)] = ready.target("select connection from _rowvioli.sources where name = 'erp'")
    assert blob and b"s3cret-pw" not in blob and b"nowhere.invalid" not in blob
    assert "s3cret-pw" not in r.stdout + r.stderr


def test_apply_needs_no_source_and_no_driver_for_it(ready):
    # the address does not resolve and no connector of this type exists
    r = apply(ready, {"erp.toml": ERP.replace('type = "postgres"', 'type = "nosuch"')})
    assert r.returncode == 0, r.stderr
    assert ready.target("select type from _rowvioli.sources") == [("nosuch",)]


def test_dollar_dollar_is_a_literal_dollar_and_needs_no_variable(ready):
    r = apply(ready, {"erp.toml": ERP.replace("$ERP_PASSWORD", "pa$$word")}, env={})
    assert r.returncode == 0, r.stderr


def test_apply_without_the_public_key_fails_and_changes_nothing(ready):
    (ready.dir / "worker.pub").unlink()
    r = apply(ready, {"erp.toml": ERP})
    assert r.returncode != 0
    assert ready.target("select count(*) from _rowvioli.sources") == [(0,)]


def test_apply_against_a_target_without_init_says_to_run_init_first(rv):
    assert rv.run("key", "new").returncode == 0
    r = apply(rv, {"erp.toml": ERP})
    assert r.returncode != 0 and "rowvioli init" in r.stderr
    assert rv.target("select count(*) from pg_namespace where nspname = '_rowvioli'") == [(0,)]


def test_apply_fails_when_two_sources_share_a_target_schema(ready):
    crm = CRM.replace('max_age = "1d"', 'max_age = "1d"\ntarget_schema = "raw_erp"')
    r = apply(ready, {"erp.toml": ERP, "crm.toml": crm})
    assert r.returncode != 0 and "raw_erp" in r.stderr
    assert ready.target("select count(*) from _rowvioli.sources") == [(0,)]


def test_apply_fails_when_a_target_schema_belongs_to_another_source_in_the_target_also_a_disabled_one(ready):
    assert apply(ready, {"erp.toml": ERP, "crm.toml": CRM}).returncode == 0
    (ready.dir / "sources" / "crm.toml").unlink()
    assert apply(ready, {"erp.toml": ERP}).returncode == 0  # crm is disabled now, raw_crm is still its schema
    before = everything(ready)
    sales = CRM.replace("[crm", "[sales").replace('max_age = "1d"', 'max_age = "1d"\ntarget_schema = "raw_crm"')
    r = apply(ready, {"sales.toml": sales})
    assert r.returncode != 0 and "raw_crm" in r.stderr and "crm" in r.stderr
    assert everything(ready) == before
    assert check(ready, {"sales.toml": sales}).returncode == 0  # --check looks only at the definition


def test_meta_holds_the_hash_of_the_definition_and_a_changed_definition_changes_it(ready):
    definition = "select definition from _rowvioli.meta"
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    [(first,)] = ready.target(definition)
    assert first
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    assert ready.target(definition) == [(first,)]
    assert apply(ready, {"erp.toml": ERP.replace('max_age = "1h"', 'max_age = "2h"')}).returncode == 0
    assert ready.target(definition) != [(first,)]


def test_a_table_overrides_the_source_settings_and_other_keys_reach_the_connector_as_options(ready):
    erp = ERP.replace('parallel = 4', 'parallel = 4\nlog = false\nmax_seconds = 60\nschema_hint = "dbo"').replace(
        '"dbo.Notes"     = {}', '"dbo.Notes"     = { log = true, max_delete_share = 0.9, max_seconds = 5, sheet = "A" }')
    r = apply(ready, {"erp.toml": erp})
    assert r.returncode == 0, r.stderr
    assert ready.target("select options from _rowvioli.sources") == [({"schema_hint": "dbo"},)]
    assert ready.target("select source_table, log, max_delete_share, max_seconds, options from _rowvioli.tables "
                        "order by 1") == [("dbo.Customers", False, Decimal("0.5"), 60, {}),
                                          ("dbo.Notes", True, Decimal("0.9"), 5, {"sheet": "A"}),
                                          ("dbo.Orders", False, Decimal("0.5"), 60, {})]


LOAD_TIMES = ERP.replace("parallel = 4", 'parallel = 4\nat = ["06:00", "14:00"]\ntimezone = "Europe/Berlin"')


def test_apply_stores_the_load_times_and_the_time_zone_of_the_source_or_the_tables_own(ready):
    erp = LOAD_TIMES.replace('max_age = "5m" }', 'at = ["23:59"], timezone = "America/New_York" }').replace(
        '"dbo.Notes"     = {}', '"dbo.Notes"     = { at = [] }')
    r = apply(ready, {"erp.toml": erp})
    assert r.returncode == 0, r.stderr
    assert ready.target("select source_table, at::text[], timezone, options from _rowvioli.tables order by 1") == [
        ("dbo.Customers", ["06:00:00", "14:00:00"], "Europe/Berlin", {}),
        ("dbo.Notes", [], "Europe/Berlin", {}),
        ("dbo.Orders", ["23:59:00"], "America/New_York", {})]
    assert ready.target("select options from _rowvioli.sources") == [({},)]


def test_changed_load_times_change_due_at_without_a_run_and_leave_what_the_workers_experienced(ready):
    assert apply(ready, {"erp.toml": ERP}).returncode == 0
    ready.target("""update _rowvioli.tables set loaded_at = '2026-01-01 00:00Z', attempted_at = '2026-01-01 00:00Z',
                           attempts = 0, requested_at = '2025-12-31 00:00Z'""")
    facts = "select loaded_at, attempted_at, attempts, requested_at from _rowvioli.tables order by id"
    due = "select due_at - loaded_at from _rowvioli.status where source_table = 'dbo.Customers'"
    before = ready.target(facts)
    assert ready.target(due) == [(timedelta(hours=1),)]
    # 01:30 in Berlin is 00:30 UTC in winter
    late = ERP.replace("parallel = 4", 'parallel = 4\nat = ["01:30", "01:45"]\ntimezone = "Europe/Berlin"')
    assert apply(ready, {"erp.toml": late}).returncode == 0
    assert ready.target(due) == [(timedelta(minutes=30),)]
    assert apply(ready, {"erp.toml": late.replace("01:30", "01:40")}).returncode == 0
    assert ready.target(due) == [(timedelta(minutes=40),)]
    assert apply(ready, {"erp.toml": late.replace("Europe/Berlin", "Europe/London")}).returncode == 0
    assert ready.target(due) == [(timedelta(hours=1),)]  # 01:30 in London is after the maximum age
    assert ready.target(facts) == before


def test_apply_with_a_time_zone_the_target_does_not_know_names_it_and_changes_nothing(ready, tmp_path):
    assert apply(ready, {"erp.toml": LOAD_TIMES}).returncode == 0
    before = everything(ready)
    # a zone this program's machine knows and the target's Postgres does not
    utc = next(p / "UTC" for p in map(Path, zoneinfo.TZPATH) if (p / "UTC").is_file())
    (tmp_path / "Mars").mkdir()
    shutil.copy(utc, tmp_path / "Mars" / "Phobos")
    changed = LOAD_TIMES.replace("Europe/Berlin", "Mars/Phobos").replace('max_age = "1h"', 'max_age = "2h"')
    r = apply(ready, {"erp.toml": changed}, env={**ENV, "PYTHONTZPATH": str(tmp_path)})
    assert r.returncode != 0 and "Mars/Phobos" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr
    assert everything(ready) == before


NO_TARGET = {"ROWVIOLI_TARGET_URL": "postgresql://nobody@nowhere.invalid:1/none"}


def check(rv, files):
    rv.definition(files)
    return rv.run("apply", "--check", "sources", env=NO_TARGET)


def test_check_passes_a_valid_definition_without_a_target_a_key_or_the_variables(rv):
    r = check(rv, {"erp.toml": ERP.replace("$ERP_PASSWORD", "$ERP_PASSWORD$$"), "crm.toml": CRM})
    assert r.returncode == 0, r.stderr


def test_check_passes_load_times_a_time_zone_without_them_and_a_source_whose_tables_all_bring_the_zone(rv):
    r = check(rv, {"erp.toml": LOAD_TIMES.replace('"dbo.Notes"     = {}', '"dbo.Notes"     = { at = [] }'),
                   "crm.toml": CRM.replace('"1d"', '"1d"\ntimezone = "UTC"')})
    assert r.returncode == 0, r.stderr
    no_source_zone = ERP.replace("parallel = 4", 'parallel = 4\nat = ["00:00", "23:59"]').replace(
        "{}", "{ at = [] }").replace(" }", ', timezone = "Asia/Kolkata" }')
    r = check(rv, {"erp.toml": no_source_zone})
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("old, new, says", [
    ('"dbo.Notes"     = {}', '"dbo.Notes"     = {', "erp.toml"),               # syntax
    ('type = "postgres"', "", "type"),                                          # required setting missing
    ('max_age = "1h"', "", "max_age"),
    ('max_age = "1h"', 'max_age = "1 hour"', "max_age"),                        # unit
    ('max_age = "1h"', 'max_age = "90"', "max_age"),
    ('max_age = "5m"', 'max_age = "5w"', "5w"),
    ("parallel = 4", 'parallel = "4"', "parallel"),                             # kind of value
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { log = "no" }', "log"),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { key = "id" }', "key"),            # keys
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { key = [] }', "key"),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = {}\n"sales.NOTES" = {}', "notes"),  # duplicate target table
    ("parallel = 4", 'parallel = 4\ntarget_schema = "raw_crm"', "raw_crm"),     # shared target schema
    ("$ERP_PASSWORD", "$erp_password", "$"),                                    # malformed placeholder
    ("$ERP_PASSWORD", "pa$", "$"),
    ('1/erp"', '1/erp"\nssl = { cert = ["pa$"] }', "connection.ssl"),           # also nested in the connection
    ('[erp.connection]\nurl = "postgresql://reader:$ERP_PASSWORD@nowhere.invalid:1/erp"\n', "", "connection"),
    ('[erp.tables]', "[erp.other]", "tables"),
    ("parallel = 4", "parallel = 0", "parallel"),                               # ranges
    ("parallel = 4", "parallel = 4\nmax_delete_share = 1.5", "max_delete_share"),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { max_delete_share = -0.1 }', "max_delete_share"),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { max_seconds = 0 }', "max_seconds"),
    ("parallel = 4", 'parallel = 4\nat = "14:00"\ntimezone = "Europe/Berlin"', "erp: at "),  # load times
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = "14:00", timezone = "Europe/Berlin" }', "dbo.Notes: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["14"], timezone = "Europe/Berlin" }', "dbo.Notes: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["6:00"], timezone = "Europe/Berlin" }', "dbo.Notes: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["14:00:00"], timezone = "Europe/Berlin" }', "dbo.Notes: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = [14:00:00], timezone = "Europe/Berlin" }', "dbo.Notes: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["14:60"], timezone = "Europe/Berlin" }', "dbo.Notes: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["06:00", "24:00"], timezone = "Europe/Berlin" }', "dbo.Notes: at '24:00'"),
    ("parallel = 4", 'parallel = 4\nat = ["25:00"]\ntimezone = "Europe/Berlin"', "erp: at "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["14:00"] }', "dbo.Notes: at needs a timezone"),
    ("parallel = 4", 'parallel = 4\nat = ["14:00"]', "dbo.Customers: at needs a timezone"),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { at = ["14:00"], timezone = "Europe/Bonn" }', "dbo.Notes: timezone "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { timezone = "" }', "dbo.Notes: timezone "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { timezone = "../x" }', "dbo.Notes: timezone "),
    ('"dbo.Notes"     = {}', '"dbo.Notes" = { timezone = "Europe" }', "dbo.Notes: timezone "),
    ("parallel = 4", 'parallel = 4\ntimezone = "Mars/Phobos"', "erp: timezone "),
])
def test_check_fails_each_invalid_definition_without_a_target_or_the_variables(rv, old, new, says):
    assert old in ERP
    r = check(rv, {"erp.toml": ERP.replace(old, new), "crm.toml": CRM})
    assert r.returncode != 0 and says in r.stderr, r.stderr
    assert "Traceback" not in r.stderr
