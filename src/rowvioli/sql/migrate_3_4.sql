-- Version 3 to 4: runs record the version of the program and of the driver (decision 11).
ALTER TABLE _rowvioli.runs ADD COLUMN program_version text, ADD COLUMN driver_version text;
UPDATE _rowvioli.meta SET schema_version = 4;
