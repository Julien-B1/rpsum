from .base import Cap, ModelInfo, Provider, TranscribeOptions
from .elevenlabs import ElevenLabs
from .local import LlamaCpp, Ollama
from .mistral import Mistral

PROVIDERS: dict[str, type[Provider]] = {
    "mistral": Mistral,
    "elevenlabs": ElevenLabs,
    "ollama": Ollama,
    "llamacpp": LlamaCpp,
}

__all__ = ["PROVIDERS", "Cap", "ModelInfo", "Provider", "TranscribeOptions"]
