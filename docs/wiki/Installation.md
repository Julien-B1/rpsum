# Installation

## Prérequis

- Linux ou WSL2.
- [`uv`](https://docs.astral.sh/uv/) pour Python (il installe Python 3.12 tout seul).
- `ffmpeg` et `ffprobe` : `sudo apt install ffmpeg`.
- Deno, requis par `yt-dlp` pour YouTube. Le binaire se place dans `bin/` à la racine du projet :

```bash
mkdir -p bin
curl -fsSL -o bin/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip
unzip bin/deno.zip -d bin && rm bin/deno.zip
```

## Installation du projet

```bash
git clone git@github.com:Julien-B1/rpsum.git
cd rpsum
uv sync
cp .env.example .env
```

## Clés

Renseigner `.env` :

| Variable | Rôle |
|---|---|
| `MISTRAL_API_KEY` | transcription Voxtral et toutes les tâches texte |
| `ELEVENLABS_API_KEY` | transcription Scribe. La permission « Speech to Text » suffit. |
| `OLLAMA_BASE_URL` | adresse du serveur Ollama, `http://localhost:11434` par défaut |
| `LLAMACPP_BASE_URL` | adresse de `llama-server`, `http://localhost:8080` par défaut |

`.env` n'est jamais commité. Les deux clés d'API sont aussi enregistrées comme secrets du dépôt GitHub.

## Vérification

```bash
uv run rpsum doctor
```

La commande indique `ok` ou `KO` pour chaque binaire et chaque fournisseur. Un fournisseur local éteint apparaît `KO` : c'est sans conséquence tant qu'aucune tâche ne l'utilise.

## Tests

```bash
uv run pytest
```
