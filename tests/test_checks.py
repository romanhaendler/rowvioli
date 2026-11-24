"""Checks, schema changes, failure reasons and secrets (spec tests 12, 13, 15, 16, 17, 18)."""
import json
import time

import psycopg
import pytest

from test_run import apply, definition, erp, ok, rows, run  # noqa: F401 (erp is a fixture)



def failed(rv, *args):
    """`run` that must fail one table; returns its reason as answered, in the status and in `runs`."""
    code, answer = run(rv, *args)
    assert code == 1, answer
    [reason] = [a["reason"] for a in answer["tables"].values() if a["status"] == "failed"]
    [(status, in_status)] = rv.target("select status, reason from _rowvioli.status where status = 'failed'")
    assert in_status == reason
    assert rv.target("select status, reason from _rowvioli.runs order by run desc limit 1") == [("failed", reason)]
    return reason


MIRROR = "select * from raw_erp.customers"


@pytest.mark.parametrize("change, expected", [
    ("insert into customers values (4, 'Dora', null); alter table customers drop constraint customers_pkey;"
     " insert into customers values (1, 'Anna2', null)", "occurs twice"),
    ("alter table customers drop constraint customers_pkey; alter table customers alter customer_no drop not null;"
     " insert into customers values (null, 'Nobody', null)", "is null"),
    ("delete from customers", "zero rows"),
    ("delete from customers where customer_no <> 1", "67 % of the rows would be deleted"),
    ("alter table customers alter customer_no type text", "column customer_no has changed its type from integer to "
     "te***t, a type of another family in the key, so a row before cannot be told from one after: give the table "
     "another target_table"),  # cases C8; the harness's password is x, which a reason hides
    ("alter table customers add column _op text", "column _op is a name of the change log"),
    ("alter table customers add column _run int", "column _run is a name of the change log"),
])
def test_a_check_fails_the_run_and_leaves_the_mirror_unchanged(erp, change, expected):
    ok(erp)
    before = rows(erp.target, MIRROR)
    for statement in change.split("; "):
        erp.source(statement)
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert expected in failed(erp)
    assert rows(erp.target, MIRROR) == before


def test_another_key_that_does_not_identify_a_row_fails_the_run_and_leaves_the_mirror_unchanged(erp):  # story 22
    ok(erp)
    before = rows(erp.target, MIRROR)
    erp.source("insert into customers values (4, 'Anna', 'Ulm')")
    apply(erp, definition(erp, '"public.customers" = { key = ["name"] }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp) == 'a key combination of ("name") occurs twice'
    assert rows(erp.target, MIRROR) == before


def test_a_table_that_lost_its_key_in_the_definition_says_so_and_names_both_ways_out(erp):
    ok(erp)
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert "no key any more" in reason and "['customer_no']" in reason, reason
    assert "put the key back" in reason and "target_table" in reason, reason
    assert "[] differs" not in reason, reason


def test_a_new_source_column_appears_in_the_mirror_and_the_change_log_with_values(erp):
    ok(erp)
    erp.source("alter table customers add column phone text")
    erp.source("update customers set phone = '0228' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")
    # a row whose new column is null equals its mirror row, so only Anna changed
    assert erp.target("select _op, customer_no, name, phone from raw_erp.customers__log where _run = "
                      "(select max(run) from _rowvioli.runs)") == [("U", 1, "Anna", "0228")]


def test_a_new_column_waits_10s_for_a_reading_consumer_then_fails_and_loads_once_the_reader_is_done(erp):
    ok(erp)
    before = rows(erp.target, MIRROR)
    erp.source("alter table customers add column phone text")
    erp.target("update _rowvioli.tables set requested_at = now()")
    with psycopg.connect(erp.target_url) as consumer:  # a long read: its transaction holds the mirror
        consumer.execute(MIRROR)
        started = time.monotonic()
        reason = failed(erp)
        # asked without waiting, as for every change of columns (story 43)
        assert reason.startswith("raw_erp.customers, its change log or its history view stayed in use for 10 s, so "
                                 "its columns could not change") and time.monotonic() - started >= 10, reason
    assert rows(erp.target, MIRROR) == before
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == rows(erp.source, "select * from customers")


def test_a_table_without_a_key_fails_when_it_would_shrink_by_more_than_max_delete_share(erp):
    apply(erp, definition(erp, '"public.notes" = {}\n'))
    ok(erp)
    before = rows(erp.target, "select * from raw_erp.notes")
    erp.source("delete from notes where txt = 'a'")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "67 % of the rows would be deleted" in failed(erp)
    assert rows(erp.target, "select * from raw_erp.notes") == before


def test_max_delete_share_of_a_table_overrides_the_sources(erp):
    text = definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 0.9 }\n')
    apply(erp, text.replace('max_age = "1h"', 'max_age = "1h"\nmax_delete_share = 0.1'))
    ok(erp)
    erp.source("delete from customers where customer_no <> 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    code, answer = run(erp)
    assert code == 0, answer
    assert answer["tables"]["raw_erp.customers"]["deleted"] == 2



def test_an_unknown_connector_type_fails_with_a_reason_naming_the_type_and_the_worker(erp):
    apply(erp, definition(erp).replace('type = "postgres"', 'type = "nosuch"'))
    reason = failed(erp)
    [(worker,)] = erp.target("select worker from _rowvioli.runs")
    assert "nosuch" in reason and worker in reason



def test_a_worker_with_the_wrong_private_key_fails_the_run_with_a_reason(erp):
    (erp.dir / "worker.key").rename(erp.dir / "old.key")
    (erp.dir / "worker.pub").rename(erp.dir / "old.pub")
    assert erp.run("key", "new").returncode == 0  # the connection stays sealed for old.pub
    reason = failed(erp)
    [(worker,)] = erp.target("select worker from _rowvioli.runs")
    assert "decrypt" in reason and worker in reason


PASSWORD, WRONG = "Sesam-0815-oeffne-dich", "Falsch-4711-geheim"


@pytest.fixture
def secret(erp):
    """erp reading the source as a role whose password is a placeholder, plus a second source crm."""
    role = "reader_" + erp.source_url.rsplit("/", 1)[1]
    erp.source(f"create role {role} login password '{PASSWORD}'")
    erp.source(f"grant select on all tables in schema public to {role}")
    url = erp.source_url.replace("postgres:x@", f"{role}:$ERP_PASSWORD@")
    text = definition(erp).replace(erp.source_url, url)
    erp.definition({"erp.toml": text, "crm.toml": text.replace("[erp", "[crm")})
    return erp


def apply_with(rv, password):
    r = rv.run("apply", "sources", env={"ERP_PASSWORD": password})
    assert r.returncode == 0, r.stderr
    return r


def leaks(rv, password, *outputs):
    """Every place a user sees text: reasons in the status and in `runs`, and the output of commands."""
    seen = [r.stdout + r.stderr for r in outputs]
    seen += [str(x) for x in rv.target("select reason from _rowvioli.tables union all select reason from _rowvioli.runs")]
    return [s for s in seen if password in s]



def test_the_stored_connection_does_not_contain_the_password(secret):
    apply_with(secret, PASSWORD)
    assert secret.target("select count(*) from _rowvioli.sources where position(convert_to(%s, 'UTF8') in connection) > 0",
                         [PASSWORD]) == [(0,)]



def test_a_ciphertext_copied_to_another_source_is_rejected(secret):
    apply_with(secret, PASSWORD)
    secret.target("update _rowvioli.sources set connection = (select connection from _rowvioli.sources where name = 'erp')"
                  " where name = 'crm'")
    assert "another source" in failed(secret, "crm")
    assert run(secret, "erp")[0] == 0


def test_two_sources_whose_sealed_connections_are_swapped_both_fail(secret):
    apply_with(secret, PASSWORD)
    secret.target("update _rowvioli.sources set connection = case name when 'erp' then (select connection from"
                  " _rowvioli.sources where name = 'crm') else (select connection from _rowvioli.sources"
                  " where name = 'erp') end")
    code, answer = run(secret)
    assert code == 1
    assert [a["reason"].count("sealed for another source") for a in answer["tables"].values()] == [1, 1]



def test_the_password_appears_nowhere_when_a_run_fails(secret):
    out = [apply_with(secret, PASSWORD)]
    apply_with(secret, PASSWORD)
    secret.definition({"erp.toml": (secret.dir / "sources" / "erp.toml").read_text()
                       .replace('"public.customers"', '"public.missing"')})
    out.append(apply_with(secret, PASSWORD))
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    assert leaks(secret, PASSWORD, *out) == []



def test_the_password_appears_nowhere_when_the_source_refuses_the_login(secret):
    out = [apply_with(secret, WRONG), secret.run("run", "erp")]
    assert out[-1].returncode == 1
    assert "password authentication failed" in secret.target("select reason from _rowvioli.runs")[0][0]
    assert leaks(secret, WRONG, *out) == []



def test_a_password_with_at_and_percent_written_plainly_loads_and_leaks_nowhere_when_refused(secret):
    plain = "Sesam@Torweg%zz-0815"
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{plain}'")
    out = [apply_with(secret, plain), secret.run("run", "erp")]
    assert out[-1].returncode == 0, out[-1].stdout + out[-1].stderr
    secret.source(f"alter role {role} password '{WRONG}'")
    secret.target("update _rowvioli.tables set requested_at = now()")
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    reason = secret.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert "password authentication failed" in reason
    for part in (plain, "Sesam", "Torweg", "zz-0815", "Sesam%40Torweg%25zz-0815"):
        assert leaks(secret, part, *out) == [], part


def test_a_password_from_a_variable_with_at_slash_and_colon_is_encoded_and_loads(secret):
    odd = "Se@sam/Tor:weg-0815"
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{odd}'")
    apply_with(secret, odd)
    assert run(secret, "erp")[0] == 0


@pytest.mark.parametrize("plain", ["Sesam[Torweg-0815", "Sesam]Torweg[0815"])
def test_a_password_with_a_bracket_written_plainly_gets_as_far_as_the_connection_and_leaks_nowhere(secret, plain):
    role = "reader_" + secret.source_url.rsplit("/", 1)[1]
    secret.source(f"alter role {role} password '{plain}'")
    text = (secret.dir / "sources" / "erp.toml").read_text().replace("$ERP_PASSWORD", plain)
    secret.definition({"erp.toml": text, "crm.toml": text.replace("[erp", "[crm")})
    out = [secret.run("apply", "sources")]
    assert out[-1].returncode == 0, out[-1].stderr
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 0, out[-1].stdout + out[-1].stderr
    secret.source(f"alter role {role} password '{WRONG}'")
    secret.target("update _rowvioli.tables set requested_at = now()")
    out.append(secret.run("run", "erp"))
    assert out[-1].returncode == 1
    reason = secret.target("select reason from _rowvioli.runs where status = 'failed'")[0][0]
    assert "password authentication failed" in reason
    for part in (plain, "Sesam", "Torweg"):
        assert leaks(secret, part, *out) == [], part


def test_a_new_empty_source_table_is_mirrored_as_an_empty_table(erp):
    erp.source("create table fresh (id int primary key, note text)")
    apply(erp, definition(erp, '"public.fresh" = { key = ["id"] }\n'))
    code, answer = run(erp)
    assert code == 0, answer
    assert erp.target("select count(*) from raw_erp.fresh") == [(0,)]


def test_an_option_postgres_does_not_know_fails_the_run_and_names_it(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], incremental = "updated" }\n'))
    assert failed(erp) == ("public.customers: the option incremental is not one of the postgres connector's; "
                           "it knows no option")


def test_an_emptied_source_publishes_when_max_delete_share_is_1(erp):
    ok(erp)
    erp.source("delete from customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "_delete_share = 1.0" in failed(erp)  # not "max_": the source's password is "x"
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 1.0 }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == []
    assert erp.target("select _op, count(*) from raw_erp.customers__log where _run = (select max(run) from "
                      "_rowvioli.runs) group by 1") == [("D", 3)]


def test_a_table_without_a_key_is_emptied_the_same_way(erp):
    apply(erp, definition(erp, '"public.customers" = {}\n'))
    ok(erp)
    erp.source("delete from customers")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert "_delete_share = 1.0" in failed(erp)
    apply(erp, definition(erp, '"public.customers" = { max_delete_share = 1.0 }\n'))
    erp.target("update _rowvioli.tables set requested_at = now()")
    ok(erp)
    assert rows(erp.target, MIRROR) == []


@pytest.mark.parametrize("value, column, state", [
    ('my "secret": value', "n::int", "22P02"), ("3000000000", "n::int", "22003"),
    # Postgres's own messages that show the value unquoted or as a name: date field value out of range: 2000-13-01,
    # relation "3000000000" does not exist
    ("3000000000", "make_date(2000, length(n) + 3, 1)", "22008"), ("3000000000", "n::regclass", "42P01")])
def test_a_value_in_the_sources_message_is_withheld_by_its_sqlstate(erp, value, column, state):  # decision 54, item 8
    erp.source("create table texts (k int, n text)")
    erp.source("insert into texts values (1, %s)", [value])
    erp.source(f"create view quoting as select k, {column} as n from texts")
    apply(erp, definition(erp, '"public.quoting" = {}\n'))
    reason = failed(erp)
    assert reason == (f"a statement raised an error (SQLSTATE {state}) in the source, reading public.quoting; its "
                      "message may hold a row's values, so it is left out here: the source's server log has it"), reason
    assert "secret" not in reason and "3000000000" not in reason and "2000-13" not in reason


def test_a_name_postgres_quotes_in_its_message_stays_in_the_reason(erp):
    ok(erp)
    erp.target("alter table raw_erp.customers add constraint c check (name <> 'Anna2')")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = failed(erp)
    assert reason.endswith('new row for relation "customers" violates check constraint "c"'), reason


def withheld(rv):
    """A run that fails one table on a message a consumer wrote; returns the reason, after making sure that the row's
    values are in none of the answer, the lines, the status and `runs`."""
    r = rv.run("run")
    assert r.returncode == 1, r.stdout
    [reason] = [a["reason"] for a in json.loads(r.stdout)["tables"].values()]
    assert rv.target("select reason from _rowvioli.status") == rv.target(
        "select reason from _rowvioli.runs order by run desc limit 1") == [(reason,)]
    assert "Anna2" not in r.stdout + r.stderr and "Secret" not in r.stdout + r.stderr, r.stdout + r.stderr
    return reason


@pytest.mark.parametrize("statement, sqlstate", [
    ("raise exception 'bad row %', NEW", "P0001"),
    ("raise exception using message = 'bad row ' || NEW::text, errcode = 'check_violation'", "23514"),
    ("assert NEW.name <> 'Anna2', 'bad row ' || NEW::text", "P0004"),
    # not raised by the code but by Postgres inside it, with the row's value: whatever the language, a message under
    # a consumer's function is withheld
    ("execute format('select from %I', NEW.name)", "42P01"),  # relation "Anna2" does not exist
    ("perform 1 / (length(NEW.name) - 5)", "22012")])
def test_a_message_a_consumers_trigger_raises_on_the_target_is_withheld_and_the_reason_names_the_function(
        erp, statement, sqlstate):
    ok(erp)
    erp.target(f"create function public.guard() returns trigger language plpgsql as $$ begin {statement}; return NEW;"
               " end $$")
    erp.target("create trigger g before insert on raw_erp.customers for each row execute function public.guard()")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert withheld(erp) == (f"function guard() raised an error (SQLSTATE {sqlstate}) in the target; its message may "
                             "hold a row's values, so it is left out here: the target's server log has it")


def test_a_message_from_a_consumers_function_in_c_that_names_no_frame_is_withheld_while_publishing(erp):
    ok(erp)  # make_date is C: its message has the value its arguments make of the row, and no frame says whose it is
    erp.target("alter table raw_erp.customers add constraint c check (make_date(2000, length(name) + 8, 1) < now())")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = withheld(erp)
    assert reason == ("a statement raised an error (SQLSTATE 22008) in the target; its message may hold a row's values, "
                      "so it is left out here: the target's server log has it"), reason


def test_an_object_a_cast_of_a_rows_value_does_not_find_is_withheld_while_publishing(erp):
    ok(erp)  # ::regclass names the value it did not find, and no frame says whose code cast it
    erp.target("alter table raw_erp.customers add constraint c check (name not like '%2' or name::regclass is not null)")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    reason = withheld(erp)
    assert reason == ("a statement raised an error (SQLSTATE 42P01) in the target; its message may hold a row's values, "
                      "so it is left out here: the target's server log has it"), reason


@pytest.mark.parametrize("statement", ["raise exception 'bad name Secret %', n",
                                       "execute format('select from %I', 'Secret' || n)"])
def test_a_message_a_function_in_a_source_view_raises_is_withheld(erp, statement):
    erp.source("create function check_name(n text) returns text language plpgsql as $$ begin "
               f"if n = 'Anna' then {statement}; end if; return n; end $$")
    erp.source("create view checked as select customer_no, check_name(name) as name from customers")
    apply(erp, definition(erp, '"public.checked" = { key = ["customer_no"] }\n'))
    state = "P0001" if "raise" in statement else "42P01"  # x is the harness's password
    assert withheld(erp) == (f"function check_name(te***t) raised an error (SQLSTATE {state}) in the source, reading "
                             "public.checked; its message may hold a row's values, so it is left out here: the "
                             "source's server log has it")


@pytest.mark.parametrize("constraint, change, says", [
    ("add constraint u unique (city)", "city = 'Essen'", 'duplicate key value violates unique constraint "u"'),
    ("add constraint f foreign key (city) references public.cities", "city = 'Ulm'",
     'violates foreign key constraint "f"'),
    ("alter name set not null", "name = null",
     'null value in column "name" of relation "customers" violates not-null constraint')])
def test_postgres_own_constraint_messages_keep_their_names(erp, constraint, change, says):
    ok(erp)
    erp.target("create table public.cities (city text primary key); insert into public.cities values ('Bonn'), ('Essen')")
    erp.target(f"alter table raw_erp.customers {constraint}")
    erp.source(f"update customers set {change} where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).endswith(says)


def test_a_source_table_created_anew_with_other_columns_says_what_it_may_be_and_the_setting_for_one_run(erp):  # H2
    ok(erp)
    erp.source("drop table customers; create table customers (customer_no int primary key, label text);"
               "insert into customers values (7, 'a'), (8, 'b'), (9, 'c')")
    erp.target("update _rowvioli.tables set requested_at = now()")
    assert failed(erp).replace("***", "x") == (  # the source's password is x, and the reason hides it
        "100 % of the rows would be deleted, more than max_delete_share = 0.5 allows: the source table may have been "
        "replaced or emptied; if so, max_delete_share = 1.0 on the table lets one run through")
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], max_delete_share = 1.0 }\n'))
    ok(erp, "erp")
    assert rows(erp.target, MIRROR) == [(7, "a"), (8, "b"), (9, "c")]


CHILD = "select * from public.branch order by customer_no"
BRANCH = ("create table public.branch () inherits (raw_erp.customers);"
          "insert into public.branch values (7, 'Gus', 'Ulm'), (8, 'Hal', 'Ulm'), (9, 'Ida', 'Ulm'), (10, 'Jo', 'Ulm')")


def test_a_consumers_table_that_inherits_from_the_mirror_keeps_its_rows_and_is_not_read_as_the_mirror(erp):
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no"], log = false }\n'))
    ok(erp)
    erp.target(BRANCH)
    branch = erp.target(CHILD)
    apply(erp, definition(erp))  # the change log begins with the mirror's rows, not the child's
    erp.source("update customers set city = 'Köln' where customer_no = 1")
    assert run(erp, "erp")[1]["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 0, "updated": 1,
                                                                 "deleted": 0}
    erp.source("update customers set city = 'Bonn' where customer_no = 1")
    assert run(erp, "erp")[1]["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 0, "updated": 1,
                                                                 "deleted": 0}
    assert erp.target(CHILD) == branch
    assert rows(erp.target, "select customer_no from only raw_erp.customers") == [(1,), (2,), (3,)]
    assert erp.target("select _op, customer_no from raw_erp.customers__log order by _run, customer_no") == [
        ("I", 1), ("I", 2), ("I", 3), ("U", 1)]


def test_a_consumers_table_that_inherits_from_the_mirror_keeps_its_rows_when_the_key_changes(erp):
    ok(erp)
    erp.target(BRANCH + ";create table public.notes () inherits (raw_erp.customers__log);"
               "insert into public.notes values (0, 'I', now(), 7, 'Gus', 'Ulm')")
    branch = erp.target(CHILD)
    apply(erp, definition(erp, '"public.customers" = { key = ["customer_no", "name"] }\n'))
    assert run(erp, "erp")[1]["tables"]["raw_erp.customers"] == {"status": "ok", "inserted": 3, "updated": 0,
                                                                 "deleted": 3}
    assert erp.target(CHILD) == branch
    assert erp.target("select count(*) from only raw_erp.customers__log "
                      "where _run = (select max(run) from _rowvioli.runs)") == [(6,)]
    # the history view reads the change log, not a consumer's table that inherits from it
    assert rows(erp.target, "select customer_no from raw_erp.customers__history where _valid_to is null") == [
        (1,), (2,), (3,)]

# a function that raises with a row's value, in a language whose frames Postgres names otherwise than PL/pgSQL's
RAISES = {"plperl": ("""elog(ERROR, "bad row $_TD->{new}{name}"); return;""",
                     """elog(ERROR, "bad name Secret$_[0]") if $_[0] eq 'Anna'; return $_[0];"""),
          "plpython3u": ("""plpy.error("bad row " + TD["new"]["name"])""",
                         """if n == "Anna": plpy.error("bad name Secret" + n)\nreturn n""")}
PL = ("the test image has PL/Perl's and PL/Python's libraries but not perl and python3: start two postgres:16-alpine "
      "containers, in both `apk add perl python3 && ln -s /usr/lib/perl5/core_perl/CORE/libperl.so /usr/lib/`, and run "
      "with ROWVIOLI_TEST_SERVERS=<source container>,<target container>")


def language(query, name):
    try:
        query(f"create extension {name}")
    except psycopg.Error:
        pytest.skip(PL)


@pytest.mark.parametrize("name", RAISES)
def test_a_message_a_consumers_trigger_in_pl_perl_or_pl_python_raises_is_withheld(erp, name):  # ticket 14, item 8
    language(erp.target, name)
    ok(erp)
    erp.target(f"create function public.guard() returns trigger language {name} as $${RAISES[name][0]}$$")
    erp.target("create trigger g before insert on raw_erp.customers for each row execute function public.guard()")
    erp.source("update customers set name = 'Anna2' where customer_no = 1")
    erp.target("update _rowvioli.tables set requested_at = now()")
    state = {"plperl": "38000", "plpython3u": "XX000"}[name]  # external_routine_exception, internal_error
    assert withheld(erp) == (f'function "guard" raised an error (SQLSTATE {state}) in the target; its message may '
                             "hold a row's values, so it is left out here: the target's server log has it")


@pytest.mark.parametrize("name", RAISES)
def test_a_message_a_function_in_pl_perl_or_pl_python_in_a_source_view_raises_is_withheld(erp, name):
    language(erp.source, name)
    erp.source(f"create function check_name(n text) returns text language {name} as $${RAISES[name][1]}$$")
    erp.source("create view checked as select customer_no, check_name(name) as name from customers")
    apply(erp, definition(erp, '"public.checked" = { key = ["customer_no"] }\n'))
    assert withheld(erp) == ('function "check_name" raised an error in the source; its message may hold a row\'s '
                             "values, so it is left out here: the source's server log has it")
