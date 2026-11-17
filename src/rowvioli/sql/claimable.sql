-- The claimable tables, most overdue first: due, not loading, and within `parallel` per source and `max_running`
-- in total, counted from the table locks held in this database (docs/target.md "How Postgres counts"). Asked by the
-- worker to know how many run processes to start, and by the claim under the counting lock (decision 34).
-- $1 and $2 narrow it to a source and a source table; '' means all.
WITH held AS (
    SELECT l.classid::int AS source_id FROM pg_locks l
     WHERE l.locktype = 'advisory' AND l.objsubid = 2 AND l.granted AND l.classid <> 0
       AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())),
due AS (
    SELECT st.id, st.source_id, src.parallel - (SELECT count(*) FROM held h WHERE h.source_id = st.source_id) AS free,
           -- most overdue: the time since due_at measured in max_ages
           extract(epoch FROM now() - st.due_at) / extract(epoch FROM st.max_age) AS overdue
      FROM _rowvioli.status st JOIN _rowvioli.sources src ON src.id = st.source_id
     WHERE st.status <> 'loading' AND st.due_at <= now()
       AND ($1::text = '' OR st.source = $1::text) AND ($2::text = '' OR st.source_table = $2::text)),
ranked AS (
    SELECT *, row_number() OVER (PARTITION BY source_id ORDER BY overdue DESC) AS n FROM due)
SELECT id, source_id, overdue FROM ranked
 WHERE n <= free
 ORDER BY overdue DESC
 LIMIT greatest((SELECT max_running FROM _rowvioli.meta) - (SELECT count(*) FROM held), 0)
