"""The view _rowvioli.status, fed with rows written by SQL (no run needed)."""
from datetime import timedelta

import psycopg
import pytest


@pytest.fixture
def table(rv):
    """Creates source 'erp' and returns a function that adds a table with the given facts."""
    assert rv.run("init").returncode == 0
    rv.target("insert into _rowvioli.sources (name, type, target_schema) values ('erp', 'postgres', 'raw_erp')")

    def add(name="t", max_age="1h", **facts):
        cols = ", ".join(["source", "source_table", "target_table", "max_age", *facts])
        vals = ", ".join(["'erp'", "%s", "%s", "%s", *(["%s"] * len(facts))])
        return rv.target(f"insert into _rowvioli.tables ({cols}) values ({vals}) returning id",
                         [name, name, max_age, *facts.values()])[0][0]
    return add


def row(rv, id, cols="status, reason"):
    return rv.target(f"select {cols} from _rowvioli.status where id = %s", [id])[0]


def pause(rv, id):
    return row(rv, id, "due_at - attempted_at")[0]


def test_the_view_has_the_columns_people_look_at(rv, table):
    table()
    cols = {r[0] for r in rv.target("select column_name from information_schema.columns"
                                    " where table_schema = '_rowvioli' and table_name = 'status'")}
    assert {"source", "source_table", "target_table", "max_age", "age", "due_at", "status", "attempts",
            "reason"} <= cols


def test_never_attempted_is_new_and_due_now(rv, table):
    id = table()
    assert row(rv, id, "status, reason, due_at = now()") == ("new", None, True)


def test_succeeded_is_ok_and_due_one_max_age_after_loading(rv, table):
    id = table(max_age="10m", loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0)
    assert row(rv, id) == ("ok", None)
    assert row(rv, id, "due_at - loaded_at")[0] == timedelta(minutes=10)


def test_failed_shows_its_reason_or_worker_lost(rv, table):
    with_reason = table("a", attempted_at="2026-01-01 00:00Z", attempts=1, reason="zero rows")
    without = table("b", attempted_at="2026-01-01 00:00Z", attempts=1)
    assert row(rv, with_reason) == ("failed", "zero rows")
    assert row(rv, without) == ("failed", "worker lost")


def test_loading_while_the_table_lock_is_held(rv, table):
    id = table(attempted_at="2026-01-01 00:00Z", attempts=1)
    source_id = row(rv, id, "source_id")[0]
    with psycopg.connect(rv.target_url, autocommit=True) as holder:
        holder.execute("select pg_advisory_lock(%s, %s)", [source_id, id])
        assert row(rv, id) == ("loading", None)
    assert row(rv, id) == ("failed", "worker lost")


def test_pause_starts_at_one_minute_and_doubles(rv, table):
    one = table("a", attempted_at="2026-01-01 00:00Z", attempts=1)
    three = table("b", attempted_at="2026-01-01 00:00Z", attempts=3)
    assert pause(rv, one) == timedelta(minutes=1)
    assert pause(rv, three) == timedelta(minutes=4)


def test_pause_never_exceeds_max_age(rv, table):
    many = table("a", max_age="1h", attempted_at="2026-01-01 00:00Z", attempts=10)
    short = table("b", max_age="30s", attempted_at="2026-01-01 00:00Z", attempts=1)
    huge = table("c", max_age="1d", attempted_at="2026-01-01 00:00Z", attempts=1000)
    assert pause(rv, many) == timedelta(hours=1)
    assert pause(rv, short) == timedelta(seconds=30)
    assert pause(rv, huge) == timedelta(days=1)


def test_failed_table_is_not_due_until_its_pause_is_over(rv, table):
    id = table(attempts=1)
    rv.target("update _rowvioli.tables set attempted_at = now() where id = %s", [id])
    assert row(rv, id, "due_at > now()")[0]
    rv.target("update _rowvioli.tables set attempted_at = now() - interval '2 minutes' where id = %s", [id])
    assert row(rv, id, "due_at <= now()")[0]


def test_a_request_after_the_last_attempt_makes_it_due_at_the_request(rv, table):
    id = table(loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0,
               requested_at="2026-01-01 00:05Z")
    assert row(rv, id, "due_at = requested_at")[0]
    rv.target("update _rowvioli.tables set attempted_at = '2026-01-01 00:06Z' where id = %s", [id])
    assert row(rv, id, "due_at - loaded_at")[0] == timedelta(hours=1)


def test_a_shortened_max_age_changes_due_at_without_a_run(rv, table):
    id = table(max_age="1h", loaded_at="2026-01-01 00:00Z", attempted_at="2026-01-01 00:00Z", attempts=0)
    rv.target("update _rowvioli.tables set max_age = '5m' where id = %s", [id])
    assert row(rv, id, "due_at - loaded_at")[0] == timedelta(minutes=5)


def test_disabled_tables_are_not_in_the_status(rv, table):
    id = table(enabled=False)
    assert rv.target("select count(*) from _rowvioli.status where id = %s", [id]) == [(0,)]


def due(rv, id):
    return f"{row(rv, id, "due_at AT TIME ZONE 'UTC'")[0]:%Y-%m-%d %H:%M}"


def test_loaded_before_a_load_time_is_due_at_that_load_time(rv, table):
    id = table(max_age="1d", at="{14:00}", timezone="Europe/Berlin",
               loaded_at="2026-06-01 11:00Z", attempted_at="2026-06-01 11:00Z", attempts=0)
    assert due(rv, id) == "2026-06-01 12:00"


def test_a_max_age_that_ends_before_the_next_load_time_makes_it_due_first(rv, table):
    id = table(max_age="30m", at="{14:00}", timezone="Europe/Berlin",
               loaded_at="2026-06-01 11:00Z", attempted_at="2026-06-01 11:00Z", attempts=0)
    assert due(rv, id) == "2026-06-01 11:30"


def test_the_earliest_load_time_after_the_last_run_began_counts_also_across_midnight(rv, table):
    morning = table("a", max_age="7d", at="{14:00,06:00}", timezone="Europe/Berlin",
                    loaded_at="2026-06-01 03:00Z", attempted_at="2026-06-01 03:00Z", attempts=0)
    evening = table("b", max_age="7d", at="{14:00,06:00}", timezone="Europe/Berlin",
                    loaded_at="2026-06-01 13:00Z", attempted_at="2026-06-01 13:00Z", attempts=0)
    assert due(rv, morning) == "2026-06-01 04:00"
    assert due(rv, evening) == "2026-06-02 04:00"


def test_a_load_time_before_the_last_run_began_does_not_make_it_due(rv, table):
    id = table(max_age="1h", at="{14:00}", timezone="Europe/Berlin",
               loaded_at="2026-06-01 12:01Z", attempted_at="2026-06-01 12:01Z", attempts=0)
    assert due(rv, id) == "2026-06-01 13:01"


def test_several_missed_load_times_give_one_run(rv, table):
    id = table(max_age="7d", at="{06:00,14:00}", timezone="Europe/Berlin",
               loaded_at="2026-06-01 03:00Z", attempted_at="2026-06-01 03:00Z", attempts=0)
    assert row(rv, id, "due_at <= now()")[0]
    rv.target("update _rowvioli.tables set attempted_at = now(), loaded_at = now() where id = %s", [id])
    assert row(rv, id, "due_at > now()")[0]


def test_a_load_time_ends_the_pause_of_a_failed_table(rv, table):
    facts = dict(max_age="1d", attempted_at="2026-06-01 11:50Z", attempts=5)
    with_load_time = table("a", at="{14:00}", timezone="Europe/Berlin", **facts)
    without = table("b", **facts)
    assert due(rv, with_load_time) == "2026-06-01 12:00"
    assert due(rv, without) == "2026-06-01 12:06"


def test_never_attempted_with_load_times_is_due_now(rv, table):
    id = table(at="{14:00}", timezone="Europe/Berlin")
    assert row(rv, id, "status, due_at = now()") == ("new", True)


def test_a_request_wins_over_a_later_load_time(rv, table):
    id = table(max_age="1d", at="{14:00}", timezone="Europe/Berlin", loaded_at="2026-06-01 03:00Z",
               attempted_at="2026-06-01 03:00Z", attempts=0, requested_at="2026-06-01 03:05Z")
    assert due(rv, id) == "2026-06-01 03:05"


def test_the_same_local_time_in_two_time_zones_is_two_points_in_time(rv, table):
    facts = dict(max_age="7d", at="{14:00}", loaded_at="2026-06-01 00:00Z", attempted_at="2026-06-01 00:00Z",
                 attempts=0)
    berlin = table("a", timezone="Europe/Berlin", **facts)
    new_york = table("b", timezone="America/New_York", **facts)
    assert due(rv, berlin) == "2026-06-01 12:00"
    assert due(rv, new_york) == "2026-06-01 18:00"


def run_at_due(rv, id):
    rv.target("update _rowvioli.tables set attempted_at = s.due_at, loaded_at = s.due_at"
              " from _rowvioli.status s where s.id = tables.id and s.id = %s", [id])


def test_a_load_time_in_the_skipped_hour_is_due_once_at_the_moved_time(rv, table):
    # 2026-03-29 in Berlin: 02:00 becomes 03:00, so 02:30 does not exist
    id = table(max_age="7d", at="{02:30}", timezone="Europe/Berlin",
               loaded_at="2026-03-28 23:00Z", attempted_at="2026-03-28 23:00Z", attempts=0)
    assert due(rv, id) == "2026-03-29 01:30"
    run_at_due(rv, id)
    assert due(rv, id) == "2026-03-30 00:30"


def test_a_load_time_in_the_repeated_hour_gives_one_run(rv, table):
    # 2026-10-25 in Berlin: 03:00 becomes 02:00, so 02:30 exists twice, at 00:30Z and at 01:30Z
    id = table(max_age="7d", at="{02:30}", timezone="Europe/Berlin",
               loaded_at="2026-10-24 22:00Z", attempted_at="2026-10-24 22:00Z", attempts=0)
    assert due(rv, id) == "2026-10-25 01:30"
    run_at_due(rv, id)
    assert due(rv, id) == "2026-10-26 01:30"


def test_load_times_without_a_time_zone_do_not_break_the_view(rv, table):
    id = table(max_age="1h", at="{14:00}", loaded_at="2026-06-01 11:00Z", attempted_at="2026-06-01 11:00Z",
               attempts=0)
    assert due(rv, id) == "2026-06-01 12:00"
