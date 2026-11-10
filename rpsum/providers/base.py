from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import httpx

from ..schema import Transcript


class Cap(StrEnum):
    STT = "stt"
    DIARIZATION = "diarization"
    AUDIO_EVENTS = "audio_events"
    WORD_TIMESTAMPS = "word_timestamps"
    CHAT = "chat"
    JSON_SCHEMA = "json_schema"
    AUDIO_CHAT = "audio_chat"


@dataclass
class ModelInfo:
    provider: str
    id: str
    caps: set[Cap] = field(default_factory=set)
    context: int | None = None


@dataclass
class TranscribeOptions:
    language: str | None = "fr"
    num_speakers: int | None = None
    vocabulary: list[str] = field(default_factory=list)
    chunk_seconds: float = 1500.0
    workdir: Path | None = None  # dossier pour les morceaux et clips intermédiaires
    progress: Callable[[str], None] = lambda message: None


class Provider:
    name = ""
    # Prix indicatif en dollars par minute d'audio, par modèle (préfixe d'identifiant).
    stt_price_per_min: dict[str, float] = {}

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    def transcribe(self, audio: Path, model: str, opts: TranscribeOptions) -> tuple[Transcript, list[dict]]:
        """Renvoie le transcript au format commun et les réponses brutes du fournisseur."""
        raise NotImplementedError(f"{self.name} ne fait pas de transcription.")

    def chat(self, model: str, messages: list[dict], json_schema: dict | None = None,
             temperature: float = 0.2) -> str:
        raise NotImplementedError(f"{self.name} ne fait pas de chat.")

    def stt_cost(self, model: str, seconds: float) -> float | None:
        for prefix, price in self.stt_price_per_min.items():
            if model.startswith(prefix):
                return round(price * seconds / 60, 4)
        return None


def openai_chat(base_url: str, api_key: str | None, model: str, messages: list[dict],
                json_schema: dict | None, temperature: float, timeout: float = 600.0) -> str:
    """Chat au format OpenAI, commun à Mistral, Ollama et llama.cpp."""
    body: dict = {"model": model, "messages": messages, "temperature": temperature}
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "reponse", "schema": json_schema, "strict": True},
        }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    for attempt in range(6):  # limite de débit ou erreur serveur : nouvel essai après 2, 4, 8, 16, 32 s
        resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
        if resp.status_code != 429 and resp.status_code < 500:
            break
        time.sleep(2 ** (attempt + 1))
    if resp.status_code >= 400:
        raise RuntimeError(f"Chat {model} : HTTP {resp.status_code} {resp.text[:500]}")
    return resp.json()["choices"][0]["message"]["content"]


def form(pairs: list[tuple[str, str]]) -> dict[str, str | list[str]]:
    """Champs de formulaire pour httpx : une clé répétée devient une liste de valeurs."""
    out: dict[str, str | list[str]] = {}
    for key, value in pairs:
        if key in out:
            current = out[key]
            out[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            out[key] = value
    return out
