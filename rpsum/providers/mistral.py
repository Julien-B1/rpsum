from __future__ import annotations

import base64
import os
import tempfile
from collections import defaultdict
from pathlib import Path

import httpx

from .. import audio as au
from ..schema import Segment, Transcript
from .base import Cap, ModelInfo, Provider, TranscribeOptions, form, openai_chat

API = "https://api.mistral.ai"
MAX_REFERENCES = 8          # limite de l'API
REF_MIN, REF_MAX = 4.0, 14.0  # l'API accepte des clips de 3 à 15 secondes
TURN_GAP = 2.0


def normalize(raw: dict, model: str, shift: float = 0.0, rename: dict[str, str] | None = None) -> list[Segment]:
    """Fusionne les segments consécutifs d'un même locuteur. `shift` replace le morceau dans la session."""
    segments: list[Segment] = []
    for item in raw.get("segments", []):
        speaker = item.get("speaker_id") or "speaker_?"
        speaker = (rename or {}).get(speaker, speaker)
        start, end, text = item["start"] + shift, item["end"] + shift, item["text"].strip()
        if not text:
            continue
        last = segments[-1] if segments else None
        if last and last.speaker == speaker and start - last.end <= TURN_GAP:
            last.text += " " + text
            last.end = end
        else:
            segments.append(Segment(start=start, end=end, speaker=speaker, text=text))
    return segments


def pick_references(raw: dict) -> dict[str, tuple[float, float]]:
    """Choisit, par locuteur, le plus long segment brut utilisable comme clip de référence.
    Garde les `MAX_REFERENCES` locuteurs qui parlent le plus."""
    best: dict[str, tuple[float, float]] = {}
    talk: dict[str, float] = defaultdict(float)
    for item in raw.get("segments", []):
        speaker, length = item.get("speaker_id"), item["end"] - item["start"]
        if not speaker:
            continue
        talk[speaker] += length
        if length >= REF_MIN and length > best.get(speaker, (0, 0))[1]:
            best[speaker] = (item["start"], min(length, REF_MAX))
    keep = sorted(best, key=lambda s: -talk[s])[:MAX_REFERENCES]
    return {s: best[s] for s in keep}


class Mistral(Provider):
    name = "mistral"
    stt_price_per_min = {"voxtral-small-transcribe": 0.004, "voxtral-mini": 0.0035}

    def _key(self) -> str:
        return os.environ["MISTRAL_API_KEY"]

    def available(self) -> tuple[bool, str]:
        return (True, "") if os.environ.get("MISTRAL_API_KEY") else (False, "MISTRAL_API_KEY absente")

    def list_models(self) -> list[ModelInfo]:
        resp = httpx.get(f"{API}/v1/models", headers={"Authorization": f"Bearer {self._key()}"}, timeout=30)
        resp.raise_for_status()
        models = []
        for item in resp.json()["data"]:
            flags = item.get("capabilities", {})
            caps: set[Cap] = set()
            if flags.get("audio_transcription"):
                # L'API n'expose pas la diarisation : tous les modèles de transcription par fichier l'ont.
                caps |= {Cap.STT, Cap.DIARIZATION}
            if flags.get("completion_chat"):
                caps |= {Cap.CHAT, Cap.JSON_SCHEMA}
            if flags.get("audio") and flags.get("completion_chat"):
                caps.add(Cap.AUDIO_CHAT)
            if flags.get("vision") and flags.get("completion_chat"):
                caps.add(Cap.VISION)
            if caps:
                models.append(ModelInfo(self.name, item["id"], caps, item.get("max_context_length")))
        return sorted(models, key=lambda m: m.id)

    def chat(self, model, messages, json_schema=None, temperature=0.2) -> str:
        return openai_chat(API, self._key(), model, messages, json_schema, temperature)

    def _request(self, audio: Path, model: str, opts: TranscribeOptions, references: dict[str, str]) -> dict:
        data: list[tuple[str, str]] = [("model", model), ("diarize", "true"), ("timestamp_granularities", "segment")]
        if opts.language:
            data.append(("language", opts.language))
        data += [("context_bias", term) for term in opts.vocabulary[:100]]
        # Forme non documentée, vérifiée par essai : un champ `speaker_references[nom]` par clip.
        data += [(f"speaker_references[{name}]", clip) for name, clip in references.items()]
        with audio.open("rb") as fh:
            resp = httpx.post(f"{API}/v1/audio/transcriptions", headers={"Authorization": f"Bearer {self._key()}"},
                              data=form(data), files={"file": (audio.name, fh)}, timeout=1800.0)
        if resp.status_code >= 400:
            raise RuntimeError(f"Mistral : HTTP {resp.status_code} {resp.text[:500]}")
        return resp.json()

    def transcribe(self, audio: Path, model: str, opts: TranscribeOptions) -> tuple[Transcript, list[dict]]:
        total = au.duration(audio)
        work = opts.workdir or Path(tempfile.mkdtemp(prefix="rpsum-"))
        work.mkdir(parents=True, exist_ok=True)
        if total <= opts.chunk_seconds * 1.2:
            plan = [(0.0, total)]
        else:
            plan = au.plan_chunks(total, au.silences(audio), opts.chunk_seconds)

        raws: list[dict] = []
        segments: list[Segment] = []
        references: dict[str, str] = {}  # nom global du locuteur -> clip en base64
        for index, (start, end) in enumerate(plan):
            piece = audio
            if len(plan) > 1:
                piece = work / f"chunk{index:02d}.opus"
                au.cut(audio, start, end - start, piece)
            opts.progress(f"Mistral : morceau {index + 1} sur {len(plan)}")
            raw = self._request(piece, model, opts, references)
            raws.append({"chunk": index, "start": start, "end": end, "response": raw})

            # Les locuteurs reconnus gardent leur nom global. Les nouveaux en reçoivent un.
            rename = {s["speaker_id"]: s["speaker_id"] for s in raw.get("segments", [])
                      if s.get("speaker_id") in references}
            for name in {s.get("speaker_id") for s in raw.get("segments", [])} - set(rename) - {None}:
                rename[name] = f"c{index}_{name}"
            segments += normalize(raw, model, shift=start, rename=rename)

            # Clips de référence pour garder les mêmes locuteurs dans les morceaux suivants.
            for local, (clip_start, clip_len) in pick_references(raw).items():
                name = rename[local]
                if name in references or len(references) >= MAX_REFERENCES:
                    continue
                clip = work / f"ref_{name}.flac"
                au.cut(piece, clip_start, clip_len, clip)
                references[name] = base64.b64encode(clip.read_bytes()).decode()

        transcript = Transcript(provider=self.name, model=model, language=opts.language, duration=total,
                                segments=segments)
        return transcript, raws
