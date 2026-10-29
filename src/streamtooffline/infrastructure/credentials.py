from __future__ import annotations

import json
from pathlib import Path


class CredentialStore:
    """Stores the user's local Soulseek credentials for reuse by the TUI."""

    def __init__(self, root: Path) -> None:
        self.path = root / ".state" / "credentials.json"

    def load(self) -> tuple[str, str]:
        if not self.path.is_file():
            return "", ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "", ""
        return str(data.get("username", "")), str(data.get("password", ""))

    def save(self, username: str, password: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"username": username, "password": password}, ensure_ascii=False),
            encoding="utf-8",
        )
