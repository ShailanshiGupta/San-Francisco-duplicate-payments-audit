"""Shared helpers used by every step."""

import os
import re

import config


class Logger:
    """Prints to the screen and keeps a copy for the step's log file."""

    def __init__(self, step_name):
        self.path = os.path.join(config.LOG_DIR, f"{step_name}.txt")
        self.lines = []

    def __call__(self, text=""):
        print(text)
        self.lines.append(str(text))

    def section(self, title):
        self("\n" + "=" * 70)
        self(title)
        self("=" * 70)

    def save(self):
        with open(self.path, "w") as f:
            f.write("\n".join(self.lines))
        print(f"\nLog saved to {self.path}")


def money(x):
    return f"${x:,.2f}" if x is not None else "$0.00"


def _sql_value(value):
    if isinstance(value, (list, tuple)):
        return ", ".join("'" + str(v).replace("'", "''") + "'" for v in value)
    return str(value)


def run_sql_file(con, filename, settings=None):
    """
    Run a SQL file from the sql/ folder through DuckDB.
    {{PLACEHOLDERS}} are filled from `settings`, comments are removed,
    and each statement runs in order. Returns the last result.
    """
    with open(os.path.join(config.SQL_DIR, filename)) as f:
        sql = f.read()
    sql = re.sub(r"--[^\n]*", "", sql)
    for key, value in (settings or {}).items():
        sql = sql.replace("{{" + key + "}}", _sql_value(value))
    leftover = re.findall(r"\{\{(\w+)\}\}", sql)
    if leftover:
        raise ValueError(f"{filename}: no setting provided for {sorted(set(leftover))}")
    result = None
    for statement in sql.split(";"):
        if statement.strip():
            result = con.execute(statement)
    return result
