"""The reason line from real driver messages, without a database."""
import pytest

from rowvioli.load import reason_line

TRACEBACK = ('. Detail: Python exception: Traceback (most recent call last):\n'
             '  File "/long/path/src/rowvioli/connectors/postgres.py", line 21, in batches\n'
             '    yield pa.record_batch(...)\n    raise convert_status(status)\n')
GET_NEXT = ("IO: nanoarrow call failed: ArrowArrayStreamGetNext(&bind.value, &current.value, &na_error) = (22) "
            "Invalid argument. ")


def reason(message, values=()):
    # a driver's own type, as ADBC's errors are: a plain Exception is the program's own reason
    return reason_line(list(values), RuntimeError(message), "reading the source")


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


def test_the_wrapper_of_a_failed_statement_goes_whatever_its_sql_holds():
    sql = "INSERT INTO t SELECT * FROM _diff\nWHERE _op IN ('I', 'U')"
    assert reason(f"ALREADY_EXISTS: [libpq] Failed to execute query '{sql}': ERROR:  duplicate key value\nDETAIL: x") \
        == "duplicate key value"
    assert reason("IO: [libpq] Failed to execute prepared statement: PGRES_FATAL_ERROR ERROR:  value too long\n") \
        == "value too long"


@pytest.mark.parametrize("password", ["x", "query", "Failed", "ERROR"])
def test_a_password_that_occurs_in_the_wrapper_does_not_keep_the_wrapper_in_the_reason(password):
    message = "IO: [libpq] Failed to execute query 'SELECT a FROM t': ERROR:  boom at x\nDETAIL: more"
    assert reason(message, [password]) == "boom at x".replace(password, "***")


def test_a_password_with_a_line_break_is_scrubbed_before_the_reason_is_cut_there():
    assert reason("cannot connect as Ge'he\nim, sorry", ["Ge'he\nim"]) == "cannot connect as ***, sorry"


def test_a_plain_exception_of_a_connector_of_ones_own_gives_its_first_line_as_a_drivers_does():
    try:  # raised outside the program, as a connector of one's own raises it; the next line may quote a row
        raise Exception("cannot read customers: duplicate key value\nDETAIL:  Key (id)=(42) already exists.")
    except Exception as e:
        assert reason_line([], e, "reading the source") == "cannot read customers: duplicate key value"


def test_a_source_table_named_columns_that_may_not_be_read_is_not_said_to_be_the_columns_table():
    assert reason("ERROR:  permission denied for table columns") == "permission denied for table columns"


WITHHELD = " raised an error in the source; its message may hold a row's values, so it is left out here: the source's " \
           "server log has it"


@pytest.mark.parametrize("message, function", [
    # the language's frames as Postgres writes them; neither image of the tests has PL/Python or PL/Perl
    ('plpy.Error: bad row Anna\nCONTEXT:  Traceback (most recent call last):\n  PL/Python function "check", line 3, '
     "in <module>\n    plpy.error('bad row ' + n)\nPL/Python function \"check\"", '"check"'),
    ('bad row Anna at line 2.\nCONTEXT:  PL/Perl function "check"', '"check"'),
    ('invalid input syntax for type integer: "Anna"\nCONTEXT:  SQL function "f" statement 1', '"f"'),
    ('relation "Anna" does not exist\nCONTEXT:  SQL statement "select from "Anna""\nPL/pgSQL function '
     'reporting.check_name(character varying) line 1 at EXECUTE', "reporting.check_name(character varying)")])
def test_a_message_under_a_consumers_function_is_withheld_whatever_its_language(message, function):
    assert reason("IO: [libpq] Execution error [PGRES_FATAL_ERROR]: ERROR:  " + message) == f"function {function}" \
        + WITHHELD


def test_postgres_own_message_of_a_violated_constraint_under_a_function_keeps_its_names():
    assert reason('IO: [libpq] Execution error [PGRES_FATAL_ERROR]: ERROR:  duplicate key value violates unique '
                  'constraint "u"\nDETAIL:  Key (id)=(1) already exists.\nCONTEXT:  SQL function "f" statement 1') \
        == 'duplicate key value violates unique constraint "u"'
