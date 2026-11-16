"""DuckDB views over a study's JSONL files (MET-08): an independent SQL route to the §6
figures, used to cross-check the Python metrics and for ad-hoc analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

FILES = ("answers", "citations", "consulted", "page_meta")


def connect(base: Path) -> Any:
    import duckdb

    con = duckdb.connect()
    data = base / "data"
    for name in FILES:
        path = data / f"{name}.jsonl"
        if path.is_file():
            literal = str(path).replace("'", "''")
            source = f"read_json_auto('{literal}', format='newline_delimited')"
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM {source}")
    con.execute(
        """
        CREATE VIEW valid_answers AS
        SELECT run, question_id, model FROM answers WHERE error IS NULL AND NOT refusal
        """
    )
    con.execute(
        """
        CREATE VIEW presence AS
        WITH pubs AS (
            SELECT DISTINCT run, question_id, model, publisher FROM citations
        ), slice AS (
            SELECT run, model, count(*) AS n FROM valid_answers GROUP BY run, model
        )
        SELECT p.run, p.model, p.publisher, count(*) AS k, s.n, count(*) / s.n AS share
        FROM pubs p
        JOIN valid_answers v USING (run, question_id, model)
        JOIN slice s USING (run, model)
        GROUP BY p.run, p.model, p.publisher, s.n
        """
    )
    return con
