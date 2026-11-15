# Shakedown 2026-11-15: wishes

Status: needs-triage

| Wish | Task / Workaround / Elsewhere | Status | From |
|---|---|---|---|
| Cast or skip a column of an unsupported type | mirror a table with `inet`, `xml`, `money` / a view with `::text` in the source, 3 lines per table / dlt column hints, Airbyte column selection | no: "Not a transformation tool" - Instead holds, if the source allows views | H2 |
| Required REST columns and a request timeout | be told when an API changes shape / gave up / dlt schema contracts, Airbyte schema checks | unlisted | H2 |
| A glob for files | a CSV that lands daily under a new name / overwrite one fixed name / Sling and dlt filesystem sources | unlisted | P4 |
| REST with wrapped answers (`{"data": [...]}`) | read a typical API / not tried / dlt and Airbyte record selector | no: README "rest" (own connector) - Instead untested | P4 |
| `apply --diff` | see what a deployment would change / `status` before and after / Terraform `plan`, dbt state | unlisted | P1 |
| Allow zero rows per table | mirror a new, empty table / wait for its first row / Sling, dlt load empty tables | no: safety limits | H2 |
