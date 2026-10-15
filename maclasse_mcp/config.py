"""Configuration par variables d'environnement. Aucun secret codé en dur.

Identifiants : MACLASSE_EMAIL + MACLASSE_PASSWORD, ou un fichier JSON
{"email": ..., "password": ...} à MACLASSE_CREDENTIALS (défaut ~/.maclasse-mcp/credentials.json,
droits 600). Le mot de passe n'est jamais journalisé ni renvoyé par un outil.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str = os.environ.get("MACLASSE_BASE_URL", "https://ecole.maclasse.photo")
    credentials_path: Path = Path(
        os.environ.get("MACLASSE_CREDENTIALS", str(Path.home() / ".maclasse-mcp" / "credentials.json"))
    )
    # Dossier local où sont enregistrés ZIP, PDF et dossiers préparés (jamais renvoyés en binaire).
    download_dir: Path = Path(
        os.environ.get("MACLASSE_DOWNLOAD_DIR", str(Path.home() / "Charlemagne" / "photos" / "maclasse"))
    )
    enable_writes: bool = os.environ.get("MACLASSE_ENABLE_WRITES", "0").lower() in ("1", "true", "oui", "yes")
    timeout: float = float(os.environ.get("MACLASSE_TIMEOUT", "180"))

    def credentials(self) -> tuple[str, str]:
        email = os.environ.get("MACLASSE_EMAIL")
        password = os.environ.get("MACLASSE_PASSWORD")
        if email and password:
            return email, password
        if self.credentials_path.exists():
            data = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            return data["email"], data["password"]
        raise RuntimeError(
            "Identifiants maclasse.photo absents : définir MACLASSE_EMAIL/MACLASSE_PASSWORD "
            f"ou créer {self.credentials_path}"
        )


SETTINGS = Settings()
