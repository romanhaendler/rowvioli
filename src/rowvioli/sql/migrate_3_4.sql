-- Version 3 to 4: runs record the version of the program and of the driver (decision 54).
ALTER TABLE _rowvioli.runs ADD COLUMN program_version text, ADD COLUMN driver_version text;
UPDATE _rowvioli.meta SET schema_version = 4;

-- The columns of every mirror and its change log (decision 54): a table, and its log and history view as for a
-- mirror (load.write_log). Written by the publishing transaction only.
CREATE TABLE _rowvioli.columns (
    target_schema text NOT NULL,
    target_table  text NOT NULL,
    "column"      text NOT NULL,
    type          text NOT NULL,
    source_type   text NOT NULL,
    "key"         int,
    mirror        boolean NOT NULL,
    was           text,
    "by"          text NOT NULL,
    note          text,
    id            int NOT NULL,
    PRIMARY KEY (target_schema, target_table, "column"));

CREATE TABLE _rowvioli.columns__log (_run bigint, _op text, _loaded_at timestamptz, LIKE _rowvioli.columns);
-- a run whose change log lost its comment on _op looks here for the last change of key (load.check)
CREATE INDEX ON _rowvioli.columns__log (id);

-- with the run and the _op of each version, and the run that ended it with that run's "by" and note, so that who may
-- read only this view reads what changed and in which run, also a column closed by hand, whose D the view leaves out
CREATE VIEW _rowvioli.columns__history AS
SELECT _valid_from, _valid_to, _valid_to_run, _valid_to_by, _valid_to_note, _run, _op, target_schema, target_table,
       "column", type, source_type, "key", mirror, was, "by", note, id
  FROM (SELECT _run, _op, _loaded_at AS _valid_from, lead(_loaded_at) OVER w AS _valid_to,
               lead(_run) OVER w AS _valid_to_run, lead("by") OVER w AS _valid_to_by, lead(note) OVER w AS _valid_to_note,
               target_schema, target_table, "column", type, source_type, "key", mirror, was, "by", note, id
          FROM _rowvioli.columns__log
        WINDOW w AS (PARTITION BY target_schema, target_table, "column" ORDER BY _loaded_at)) h
 WHERE _op <> 'D';
