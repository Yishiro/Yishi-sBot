from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import psycopg
except ImportError:
    psycopg = None


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

CONFIG_FILE = DATA_DIR / "config.json"
TICKETS_FILE = DATA_DIR / "tickets.json"
WARNINGS_FILE = DATA_DIR / "warnings.json"
INVITES_FILE = DATA_DIR / "invites.json"
GIVEAWAYS_FILE = DATA_DIR / "giveaways.json"
GACHA_FILE = DATA_DIR / "gacha.json"
SALES_FILE = DATA_DIR / "sales.json"
PROMOS_FILE = DATA_DIR / "promos.json"
LEVELS_FILE = DATA_DIR / "levels.json"

DATABASE_URL = os.getenv("DATABASE_URL")
STATE_TABLE_NAME = "bot_state"
_db_ready = False


def _clone_data(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(data))


def _storage_key(path: Path) -> str:
    return path.name


def _read_local_json(path: Path, default: dict[str, Any], *, repair_file: bool) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        if repair_file:
            path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return _clone_data(default)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        if repair_file:
            path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return _clone_data(default)


def _require_database_driver() -> None:
    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL est défini, mais psycopg n'est pas installé. "
            "Ajoute les dépendances puis redéploie le bot."
        )


def _ensure_database_ready() -> None:
    global _db_ready
    if _db_ready or not DATABASE_URL:
        return

    _require_database_driver()
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {STATE_TABLE_NAME} (
                    state_key TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        connection.commit()
    _db_ready = True


def _load_from_database(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    _ensure_database_ready()
    state_key = _storage_key(path)

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT data FROM {STATE_TABLE_NAME} WHERE state_key = %s",
                (state_key,),
            )
            row = cursor.fetchone()

        if row is not None and isinstance(row[0], dict):
            return _clone_data(row[0])

    migrated_data = _read_local_json(path, default, repair_file=False)
    _save_to_database(path, migrated_data)
    return _clone_data(migrated_data)


def _save_to_database(path: Path, data: dict[str, Any]) -> None:
    _ensure_database_ready()
    state_key = _storage_key(path)

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {STATE_TABLE_NAME} (state_key, data, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (state_key)
                DO UPDATE SET
                    data = EXCLUDED.data,
                    updated_at = NOW()
                """,
                (state_key, json.dumps(data)),
            )
        connection.commit()


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if DATABASE_URL:
        return _load_from_database(path, default)
    return _read_local_json(path, default, repair_file=True)


def save_json(path: Path, data: dict[str, Any]) -> None:
    if DATABASE_URL:
        _save_to_database(path, data)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temp_path, path)
