from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path.cwd()
RUNS = ROOT / "runs"


def load() -> dict:
    load_dotenv(ROOT / ".env")
    # Deno local, requis par yt-dlp pour YouTube.
    os.environ["PATH"] = f"{ROOT / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
    path = ROOT / "config.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}


def task_choice(cfg: dict, task: str, provider: str | None, model: str | None) -> tuple[str, str]:
    base = cfg.get("tasks", {}).get(task, {})
    chosen_provider = provider or base.get("provider")
    # Le modèle du fichier de config ne vaut que pour le fournisseur du fichier de config.
    chosen_model = model or (base.get("model") if chosen_provider == base.get("provider") else None)
    if not chosen_provider or not chosen_model:
        raise SystemExit(f"Tâche « {task} » : précise --provider et --model, ou renseigne config.toml.")
    return chosen_provider, chosen_model


def run_dir(run_id: str) -> Path:
    path = RUNS / run_id
    if not path.is_dir():
        raise SystemExit(f"Run inconnu : {run_id} (dossier {path} absent).")
    return path
