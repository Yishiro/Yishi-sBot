import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
TICKETS_FILE = BASE_DIR / "tickets.json"
WARNINGS_FILE = BASE_DIR / "warnings.json"


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return json.loads(json.dumps(default))

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return json.loads(json.dumps(default))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
