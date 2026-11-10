# Fournisseurs et modèles

Chaque tâche a son fournisseur et son modèle. Le réglage par défaut est dans `config.toml` :

```toml
[tasks.transcribe]
provider = "elevenlabs"
model = "scribe_v2"

[tasks.summarize]
provider = "mistral"
model = "mistral-large-latest"
```

Les tâches sont `transcribe`, `identify`, `enrich`, `summarize` et `extract`. Les options `--provider` et `--model` d'une commande l'emportent sur le fichier.

## Compatibilité

Un modèle n'est accepté que s'il a les capacités exigées par la tâche. Sinon la commande s'arrête et liste les modèles compatibles.

| Tâche | Capacités exigées |
|---|---|
| `transcribe` | `stt`, `diarization` |
| `identify` | `chat`, `json_schema` |
| `enrich` | `chat` |
| `summarize` | `chat` |
| `extract` | `chat`, `json_schema` |

```bash
uv run rpsum models --task transcribe
```

Les listes de modèles sont lues en direct auprès de Mistral, d'Ollama et de llama.cpp. Celle d'ElevenLabs est fixe.

## Les fournisseurs

| Fournisseur | Nom | Transcription | Tâches texte | Remarques |
|---|---|---|---|---|
| ElevenLabs | `elevenlabs` | oui | non | une requête par session, sons balisés (`[rire]`), horodatage au mot |
| Mistral | `mistral` | oui | oui | transcription par morceaux de 25 minutes, sans balisage des sons |
| Ollama | `ollama` | non | oui | pas encore testé sur un serveur réel |
| llama.cpp | `llamacpp` | non | oui | pas encore testé sur un serveur réel |

## Transcription : ElevenLabs ou Mistral

Sur les deux sessions d'essai, ElevenLabs a mieux séparé les voix et il est le seul à signaler les rires, utiles pour le bêtisier. Il est le choix par défaut. Les coûts sont voisins : environ 0,65 dollar pour une session de 2 h 50.

Avec Mistral, la session est découpée sur les silences. Des clips de référence, tirés du premier morceau, servent à garder les mêmes locuteurs d'un morceau à l'autre. La taille des morceaux se règle dans `config.toml` (`mistral_chunk_seconds`).

## Modèles locaux

Lancer Ollama ou `llama-server` sur la machine qui a le GPU, puis donner son adresse dans `.env`. Exemple :

```bash
OLLAMA_BASE_URL=http://192.168.1.20:11434
uv run rpsum models --task summarize
uv run rpsum summarize ma-session --provider ollama --model <modèle>
```
