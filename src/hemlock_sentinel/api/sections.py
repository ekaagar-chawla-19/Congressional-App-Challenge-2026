"""Named sections of a forest (a rectangle on the map) that the user analyses on their own.

Stored next to the forest's tree database. A section is just an area: trees are in it when
their latest location falls inside, so sections may overlap and need no maintenance.
"""

from __future__ import annotations

import time

from ..database.repository import TreeRepository

SCHEMA = """CREATE TABLE IF NOT EXISTS sections (
    section_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    west REAL NOT NULL, south REAL NOT NULL, east REAL NOT NULL, north REAL NOT NULL,
    created_at REAL NOT NULL)"""


def ensure_schema(repo: TreeRepository) -> None:
    with repo.tx() as c:
        c.execute(SCHEMA)


def _row(r) -> dict:
    return {"section_id": r["section_id"], "name": r["name"],
            "bbox": [r["west"], r["south"], r["east"], r["north"]], "created_at": r["created_at"]}


def list_sections(repo: TreeRepository) -> list[dict]:
    return [_row(r) for r in repo.query("SELECT * FROM sections ORDER BY name")]


def get_section(repo: TreeRepository, section_id: int) -> dict | None:
    rows = repo.query("SELECT * FROM sections WHERE section_id=?", (section_id,))
    return _row(rows[0]) if rows else None


def create_section(repo: TreeRepository, name: str, bbox: tuple[float, float, float, float]) -> dict:
    if any(s["name"].lower() == name.strip().lower() for s in list_sections(repo)):
        raise ValueError(f"a section called {name.strip()!r} already exists")
    with repo.tx() as c:
        cur = c.execute("INSERT INTO sections(name, west, south, east, north, created_at) VALUES(?,?,?,?,?,?)",
                        (name.strip(), *bbox, time.time()))
    return get_section(repo, cur.lastrowid)


def delete_section(repo: TreeRepository, section_id: int) -> bool:
    with repo.tx() as c:
        return c.execute("DELETE FROM sections WHERE section_id=?", (section_id,)).rowcount > 0
