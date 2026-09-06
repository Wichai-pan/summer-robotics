#!/usr/bin/env python3
"""Read-only structural audit for an RTAB-Map candidate database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


LINK_NAMES = {
    0: "neighbor",
    1: "global_closure",
    2: "local_space_closure",
    3: "local_time_closure",
    4: "user_closure",
    5: "virtual_closure",
    6: "neighbor_merged",
    7: "pose_prior",
    8: "landmark",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    database = args.database.resolve()
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    link_counts = {
        LINK_NAMES.get(int(link_type), str(link_type)): int(count)
        for link_type, count in connection.execute(
            "SELECT type, count(*) FROM Link GROUP BY type ORDER BY type"
        )
    }
    node_weights = {
        str(weight): int(count)
        for weight, count in connection.execute(
            "SELECT weight, count(*) FROM Node GROUP BY weight ORDER BY weight"
        )
    }
    sensor_rows = connection.execute(
        "SELECT sum(length(image)>0), sum(length(depth)>0), "
        "sum(length(ground_cells)>0), sum(length(obstacle_cells)>0), "
        "sum(length(empty_cells)>0) FROM Data"
    ).fetchone()
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    database_hash = sha256(database)
    original_hash = sha256(args.original.resolve()) if args.original else None
    payload = {
        "status": "PASS"
        if integrity == [("ok",)] and not violations and (original_hash in (None, database_hash))
        else "FAIL",
        "database": str(database),
        "bytes": database.stat().st_size,
        "sha256": database_hash,
        "original_sha256": original_hash,
        "identical_to_original": original_hash == database_hash if original_hash else None,
        "integrity_check": [row[0] for row in integrity],
        "foreign_key_violations": len(violations),
        "sessions": scalar(connection, "SELECT count(DISTINCT map_id) FROM Node"),
        "nodes": scalar(connection, "SELECT count(*) FROM Node"),
        "nodes_by_weight": node_weights,
        "links": scalar(connection, "SELECT count(*) FROM Link"),
        "links_by_type": link_counts,
        "words": scalar(connection, "SELECT count(*) FROM Word"),
        "features": scalar(connection, "SELECT count(*) FROM Feature"),
        "sensor_rows": dict(
            zip(
                ("rgb", "depth", "ground_grid", "obstacle_grid", "empty_grid"),
                (int(value or 0) for value in sensor_rows),
            )
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
