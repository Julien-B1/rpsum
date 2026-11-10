"""Suivi de consommation des API.

Mistral n'expose aucune API de quota ou de facturation : chaque appel est donc noté ici, dans
`runs/usage.jsonl`, avec les jetons ou les secondes d'audio facturés et un coût indicatif.
ElevenLabs expose sa consommation (`/v1/usage/character-stats`), et la limite de l'abonnement
(`/v1/user/subscription`) seulement si la clé a la permission `user_read`.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "runs" / "usage.jsonl"
_lock = threading.Lock()

# Prix indicatifs en dollars par million de jetons (entrée, sortie), par préfixe d'identifiant.
# À vérifier sur https://mistral.ai/pricing : ils changent sans préavis.
CHAT_PRICES = {
    "mistral-large": (0.5, 1.5),
    "mistral-medium": (0.4, 2.0),
    "mistral-small": (0.1, 0.3),
    "ministral": (0.1, 0.1),
    "magistral-medium": (2.0, 5.0),
    "magistral-small": (0.5, 1.5),
}

MISTRAL_CONSOLE = "https://admin.mistral.ai/organization/usage"
ELEVENLABS_CONSOLE = "https://elevenlabs.io/app/subscription"


def chat_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    for prefix, (price_in, price_out) in CHAT_PRICES.items():
        if model.startswith(prefix):
            return round((prompt_tokens * price_in + completion_tokens * price_out) / 1e6, 5)
    return None


def record(provider: str, model: str, kind: str, **fields) -> None:
    """Ajoute une ligne au journal. Ne doit jamais faire échouer un traitement."""
    entry = {"at": datetime.now().isoformat(timespec="seconds"), "provider": provider, "model": model,
             "kind": kind, **fields}
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with _lock, LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def rate_limits(headers: httpx.Headers) -> dict[str, str]:
    return {k.removeprefix("x-ratelimit-"): v for k, v in headers.items() if k.startswith("x-ratelimit-")}


def read_ledger(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def totals(rows: list[dict], since: str = "") -> dict[str, dict]:
    """Totaux par fournisseur depuis une date ISO (« 2026-11 » pour le mois)."""
    out: dict[str, dict] = {}
    for row in rows:
        if row.get("at", "") < since:
            continue
        t = out.setdefault(row["provider"], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                             "audio_seconds": 0.0, "cost_usd": 0.0})
        t["calls"] += 1
        t["prompt_tokens"] += row.get("prompt_tokens", 0)
        t["completion_tokens"] += row.get("completion_tokens", 0)
        t["audio_seconds"] += row.get("audio_seconds", 0.0)
        t["cost_usd"] += row.get("cost_usd") or 0.0
    return out


def elevenlabs_status(days: int = 30) -> dict:
    """Abonnement (si permis) et crédits consommés par produit sur les derniers jours."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return {"error": "ELEVENLABS_API_KEY absente"}
    headers = {"xi-api-key": key}
    out: dict = {}
    resp = httpx.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers, timeout=20)
    if resp.status_code == 200:
        sub = resp.json()
        out["subscription"] = {
            "tier": sub.get("tier"),
            "used": sub.get("character_count"),
            "limit": sub.get("character_limit"),
            "reset": sub.get("next_character_count_reset_unix"),
        }
    else:
        detail = resp.json().get("detail", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
        out["subscription_error"] = detail.get("message") if isinstance(detail, dict) else str(detail)
    end = int(time.time() * 1000)
    resp = httpx.get("https://api.elevenlabs.io/v1/usage/character-stats", headers=headers, timeout=20, params={
        "start_unix": end - days * 86_400_000, "end_unix": end,
        "aggregation_interval": "day", "breakdown_type": "product_type"})
    if resp.status_code == 200:
        data = resp.json()
        out["days"] = [datetime.fromtimestamp(t / 1000).date().isoformat() for t in data.get("time", [])]
        out["by_product"] = {k: v for k, v in data.get("usage", {}).items() if any(v)}
    else:
        out["stats_error"] = f"HTTP {resp.status_code} {resp.text[:200]}"
    return out


def mistral_limits() -> dict[str, str]:
    """Limites de débit courantes, lues sur les en-têtes d'un appel de 1 jeton (coût négligeable)."""
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        return {"error": "MISTRAL_API_KEY absente"}
    resp = httpx.post("https://api.mistral.ai/v1/chat/completions", timeout=20,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": "mistral-small-latest", "max_tokens": 1,
                            "messages": [{"role": "user", "content": "ok"}]})
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code} {resp.text[:200]}"}
    return rate_limits(resp.headers)
