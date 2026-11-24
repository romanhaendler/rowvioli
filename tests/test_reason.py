"""The reason line from real driver messages, without a database."""
from rowvioli.load import reason_line

TRACEBACK = ('. Detail: Python exception: Traceback (most recent call last):\n'
             '  File "/long/path/src/rowvioli/connectors/postgres.py", line 21, in batches\n'
             '    yield pa.record_batch(...)\n    raise convert_status(status)\n')
GET_NEXT = ("IO: nanoarrow call failed: ArrowArrayStreamGetNext(&bind.value, &current.value, &na_error) = (22) "
            "Invalid argument. ")


def reason(message, values=()):
    return reason_line(list(values), Exception(message), "reading the source")


def test_a_cut_message_with_a_traceback_gives_the_cause_before_it():
    assert reason(GET_NEXT + "Invalid: The string 'nan' is not a valid decimal256 number" + TRACEBACK
                  + "pyarrow.lib.") == "The string 'nan' is not a valid decimal256 number."
    assert reason(GET_NEXT + "Invalid: Rescaling Decimal value would cause data loss" + TRACEBACK
                  + "pyarrow.lib.Arro") == "Rescaling Decimal value would cause data loss."


def test_a_connector_exception_inside_a_traceback_is_scrubbed_first():
    message = GET_NEXT + "Unknown error: cannot connect as geheim" + TRACEBACK + "RuntimeError: cannot connect as geheim"
    assert reason(message, ["geheim"]) == "cannot connect as ***."


def test_a_bare_traceback_gives_its_last_line():
    assert reason("Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: bad") == "ValueError: bad"


def test_a_line_ending_in_a_colon_is_joined_with_the_next():
    message = ("ODBC emitted an error calling 'SQLDriverConnect':\nState: 08001, Native error: 101, Message: FATAL:  "
               "password authentication failed for user \"reader\"\nmore")
    assert reason(message) == ("ODBC emitted an error calling 'SQLDriverConnect': State: 08001, Native error: 101, "
                               "Message: FATAL:  password authentication failed for user \"reader\"")


def test_a_value_postgres_quotes_in_its_message_stays_out_and_a_name_stays_in():
    source = ("IO: nanoarrow call failed: ArrowArrayStreamGetNext(&bind.value, &current.value, &na_error) = (5) "
              "Input/output error. IOError: [libpq] Execution error [PGRES_FATAL_ERROR]: ERROR:  ")
    assert reason(source + 'invalid input syntax for type integer: "my "secret": value"\nCONTEXT: x').endswith(
        'invalid input syntax for type integer: "***"')
    assert reason(source + 'value "3000000000" is out of range for type integer').endswith(
        'value "***" is out of range for type integer')
    assert reason('ERROR:  new row for relation "customers" violates check constraint "c"\nDETAIL: Failing row') \
        == 'new row for relation "customers" violates check constraint "c"'


def test_the_wrapper_of_a_failed_statement_goes_whatever_its_sql_holds():
    sql = "INSERT INTO t SELECT * FROM _diff\nWHERE _op IN ('I', 'U')"
    assert reason(f"ALREADY_EXISTS: [libpq] Failed to execute query '{sql}': ERROR:  duplicate key value\nDETAIL: x") \
        == "duplicate key value"
    assert reason("IO: [libpq] Failed to execute prepared statement: PGRES_FATAL_ERROR ERROR:  value too long\n") \
        == "value too long"
