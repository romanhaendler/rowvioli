\set ON_ERROR_STOP on
CREATE SCHEMA _etl;
CREATE TABLE _etl.sources (id serial PRIMARY KEY, name text UNIQUE, parallel int NOT NULL);
CREATE TABLE _etl.tables  (id serial PRIMARY KEY, quelle_id int REFERENCES _etl.sources, zieltabelle text UNIQUE);
CREATE TABLE _etl.runs (lauf bigserial PRIMARY KEY, auftrag bigint, quelle_id int, tabelle_id int,
  status text NOT NULL DEFAULT 'wartet', versuch int NOT NULL DEFAULT 1, worker text, start timestamptz, ende timestamptz, grund text);
CREATE UNIQUE INDEX ON _etl.runs (tabelle_id) WHERE status = 'wartet';

-- Sperre gehalten? Zwei-Schluessel-Form: classid = Quelle, objid = Tabelle, objsubid = 2
CREATE FUNCTION _etl.locked(q int, t int) RETURNS boolean LANGUAGE sql AS $$
  SELECT EXISTS (SELECT 1 FROM pg_locks l WHERE l.locktype='advisory' AND l.objsubid=2 AND l.granted
     AND l.classid=q AND l.objid=t AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database())) $$;

CREATE FUNCTION _etl.claim(p_worker text) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE s record; r record; busy int; d record;
BEGIN
  -- 1. gestorbene Laeufe: als laufend eingetragen, aber niemand haelt die Sperre
  FOR d IN UPDATE _etl.runs SET status='gestorben', ende=now(), grund='Worker ausgefallen'
           WHERE status='läuft' AND NOT _etl.locked(quelle_id, tabelle_id) RETURNING * LOOP
    IF d.versuch < 3 THEN
      INSERT INTO _etl.runs (auftrag, quelle_id, tabelle_id, versuch) VALUES (d.auftrag, d.quelle_id, d.tabelle_id, d.versuch+1)
      ON CONFLICT DO NOTHING;
    END IF;
  END LOOP;
  -- 2. naechste wartende Tabelle einer Quelle, die noch Platz hat
  FOR s IN SELECT q.id, q.parallel FROM _etl.sources q
           WHERE EXISTS (SELECT 1 FROM _etl.runs WHERE quelle_id=q.id AND status='wartet') ORDER BY q.id LOOP
    PERFORM pg_advisory_xact_lock(0, s.id);            -- nur ein Worker zaehlt je Quelle gleichzeitig
    SELECT count(*) INTO busy FROM pg_locks l WHERE l.locktype='advisory' AND l.objsubid=2 AND l.granted
       AND l.classid=s.id AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database());
    CONTINUE WHEN busy >= s.parallel;
    FOR r IN SELECT lauf, tabelle_id FROM _etl.runs WHERE quelle_id=s.id AND status='wartet' ORDER BY lauf LOOP
      IF pg_try_advisory_lock(s.id, r.tabelle_id) THEN  -- Sitzungssperre: bleibt nach dem COMMIT
        UPDATE _etl.runs SET status='läuft', worker=p_worker, start=now() WHERE lauf=r.lauf;
        RETURN r.lauf;
      END IF;
    END LOOP;
  END LOOP;
  RETURN NULL;
END $$;
CREATE FUNCTION _etl.done(p bigint) RETURNS void LANGUAGE sql AS $$ UPDATE _etl.runs SET status='ok', ende=now() WHERE lauf=p $$;
CREATE FUNCTION _etl.unlock(p bigint) RETURNS void LANGUAGE sql AS $$ SELECT pg_advisory_unlock(quelle_id, tabelle_id) FROM _etl.runs WHERE lauf=p $$;

INSERT INTO _etl.sources (name, parallel) VALUES ('erp', 4), ('crm', 2);
INSERT INTO _etl.tables (quelle_id, zieltabelle) SELECT 1, 'raw_erp.t'||g FROM generate_series(1,40) g;
INSERT INTO _etl.tables (quelle_id, zieltabelle) SELECT 2, 'raw_crm.t'||g FROM generate_series(1,10) g;
INSERT INTO _etl.runs (auftrag, quelle_id, tabelle_id) SELECT quelle_id, quelle_id, id FROM _etl.tables;
CREATE TABLE probe (erp int, crm int);
