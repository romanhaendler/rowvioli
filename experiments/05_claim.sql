\set ON_ERROR_STOP on
CREATE SCHEMA _rowvioli;
CREATE TABLE _rowvioli.sources (id serial PRIMARY KEY, name text UNIQUE, parallel int NOT NULL);
CREATE TABLE _rowvioli.tables  (id serial PRIMARY KEY, source_id int REFERENCES _rowvioli.sources, target_table text UNIQUE);
CREATE TABLE _rowvioli.runs (run bigserial PRIMARY KEY, order_id bigint, source_id int, table_id int,
  status text NOT NULL DEFAULT 'waiting', attempt int NOT NULL DEFAULT 1, worker text, start timestamptz, finished timestamptz, reason text);
CREATE UNIQUE INDEX ON _rowvioli.runs (table_id) WHERE status = 'waiting';

-- Lock held? Two-key form: classid = source, objid = table, objsubid = 2
CREATE FUNCTION _rowvioli.locked(q int, t int) RETURNS boolean LANGUAGE sql AS $$
  SELECT EXISTS (SELECT 1 FROM pg_locks l WHERE l.locktype='advisory' AND l.objsubid=2 AND l.granted
     AND l.classid=q AND l.objid=t AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database())) $$;

CREATE FUNCTION _rowvioli.claim(p_worker text) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE s record; r record; busy int; d record;
BEGIN
  -- 1. dead runs: recorded as running, but nobody holds the lock
  FOR d IN UPDATE _rowvioli.runs SET status='dead', finished=now(), reason='worker lost'
           WHERE status='running' AND NOT _rowvioli.locked(source_id, table_id) RETURNING * LOOP
    IF d.attempt < 3 THEN
      INSERT INTO _rowvioli.runs (order_id, source_id, table_id, attempt) VALUES (d.order_id, d.source_id, d.table_id, d.attempt+1)
      ON CONFLICT DO NOTHING;
    END IF;
  END LOOP;
  -- 2. next waiting table of a source that still has room
  FOR s IN SELECT q.id, q.parallel FROM _rowvioli.sources q
           WHERE EXISTS (SELECT 1 FROM _rowvioli.runs WHERE source_id=q.id AND status='waiting') ORDER BY q.id LOOP
    PERFORM pg_advisory_xact_lock(0, s.id);            -- only one worker counts per source at a time
    SELECT count(*) INTO busy FROM pg_locks l WHERE l.locktype='advisory' AND l.objsubid=2 AND l.granted
       AND l.classid=s.id AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database());
    CONTINUE WHEN busy >= s.parallel;
    FOR r IN SELECT run, table_id FROM _rowvioli.runs WHERE source_id=s.id AND status='waiting' ORDER BY run LOOP
      IF pg_try_advisory_lock(s.id, r.table_id) THEN  -- session lock: stays after the COMMIT
        UPDATE _rowvioli.runs SET status='running', worker=p_worker, start=now() WHERE run=r.run;
        RETURN r.run;
      END IF;
    END LOOP;
  END LOOP;
  RETURN NULL;
END $$;
CREATE FUNCTION _rowvioli.done(p bigint) RETURNS void LANGUAGE sql AS $$ UPDATE _rowvioli.runs SET status='ok', finished=now() WHERE run=p $$;
CREATE FUNCTION _rowvioli.unlock(p bigint) RETURNS void LANGUAGE sql AS $$ SELECT pg_advisory_unlock(source_id, table_id) FROM _rowvioli.runs WHERE run=p $$;

INSERT INTO _rowvioli.sources (name, parallel) VALUES ('erp', 4), ('crm', 2);
INSERT INTO _rowvioli.tables (source_id, target_table) SELECT 1, 'raw_erp.t'||g FROM generate_series(1,40) g;
INSERT INTO _rowvioli.tables (source_id, target_table) SELECT 2, 'raw_crm.t'||g FROM generate_series(1,10) g;
INSERT INTO _rowvioli.runs (order_id, source_id, table_id) SELECT source_id, source_id, id FROM _rowvioli.tables;
CREATE TABLE probe (erp int, crm int);
