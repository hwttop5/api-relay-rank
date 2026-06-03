#!/usr/bin/env python3
from __future__ import annotations

import json

try:
    from scripts.database import database_url, ensure_database
except ModuleNotFoundError:
    from database import database_url, ensure_database


def main() -> int:
    dsn = database_url()
    ensure_database(dsn)
    print(json.dumps({"ok": True, "database": dsn.split("@", 1)[-1] if "@" in dsn else "configured"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
