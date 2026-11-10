"""Fournisseurs locaux : Ollama et llama.cpp. Texte seulement pour l'instant.
La transcription locale (Whisper + pyannote) reste à faire sur la machine qui a le GPU."""
from __future__ import annotations

import os

import httpx

from .base import Cap, ModelInfo, Provider, openai_chat


class _Local(Provider):
    env = ""
    default_url = ""

    @property
    def base_url(self) -> str:
        return os.environ.get(self.env, self.default_url).rstrip("/")

    def available(self) -> tuple[bool, str]:
        try:
            self.list_models()
            return True, ""
        except httpx.HTTPError as exc:
            return False, f"{self.base_url} injoignable ({type(exc).__name__})"

    def chat(self, model, messages, json_schema=None, temperature=0.2) -> str:
        return openai_chat(self.base_url, None, model, messages, json_schema, temperature, timeout=3600.0)


class Ollama(_Local):
    name = "ollama"
    env, default_url = "OLLAMA_BASE_URL", "http://localhost:11434"

    def list_models(self) -> list[ModelInfo]:
        resp = httpx.get(f"{self.base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = []
        for item in resp.json().get("models", []):
            show = httpx.post(f"{self.base_url}/api/show", json={"model": item["name"]}, timeout=10)
            declared = show.json().get("capabilities", ["completion"]) if show.status_code == 200 else ["completion"]
            if "completion" in declared:  # exclut les modèles d'embedding
                caps = {Cap.CHAT, Cap.JSON_SCHEMA} | ({Cap.VISION} if "vision" in declared else set())
                models.append(ModelInfo(self.name, item["name"], caps))
        return models


class LlamaCpp(_Local):
    name = "llamacpp"
    env, default_url = "LLAMACPP_BASE_URL", "http://localhost:8080"

    def list_models(self) -> list[ModelInfo]:
        resp = httpx.get(f"{self.base_url}/v1/models", timeout=5)
        resp.raise_for_status()
        return [ModelInfo(self.name, item["id"], {Cap.CHAT, Cap.JSON_SCHEMA}) for item in resp.json().get("data", [])]
