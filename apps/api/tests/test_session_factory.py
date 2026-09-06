"""Sessions are created in one place, so substituting one reaches every query.

``get_db`` is the seam a deployment overrides to supply its own session: the
suite in conftest does it, and so does anything wanting a read replica, an
instrumented session or a different engine. Code that calls the sessionmaker
directly opts out of that seam, and because such code runs outside a request,
the resulting failure surfaces inside a background task instead of in a
response.

The scan is token-based rather than a line regex. A regex over raw text also
flags the name inside a comment or a docstring, which punishes exactly the
code that explains the rule — a rule you cannot write down is a badly
implemented rule. Tokenising drops comments and strings for free, while a real
call is always a NAME token followed by an opening parenthesis, so nothing the
regex caught can slip through.
"""

import io
import pathlib
import tokenize

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
SESSIONMAKER = "SessionLocal"


def _call_lines(source: str) -> list[int]:
    """Line numbers where the sessionmaker is actually called."""
    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
    ]
    return [
        current.start[0]
        for current, following in zip(tokens, tokens[1:])
        if current.type == tokenize.NAME and current.string == SESSIONMAKER and following.string == "("
    ]


def test_only_database_module_calls_the_sessionmaker():
    offenders = []
    for path in APP.rglob("*.py"):
        if path.name == "database.py":
            continue  # where the sessionmaker lives and is legitimately called
        for number in _call_lines(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(APP.parent)}:{number}")

    assert not offenders, (
        "These call the sessionmaker directly and so bypass get_db, which means a "
        "substituted session never reaches them. Use new_session() from "
        "app.database instead:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_reads_code_and_not_prose():
    """The guard must catch a call and ignore a mention of one."""
    assert _call_lines("db = SessionLocal()\n") == [1]
    assert _call_lines("# never call SessionLocal() from here\n") == []
    assert _call_lines('"""Calling SessionLocal() directly bypasses get_db."""\n') == []
