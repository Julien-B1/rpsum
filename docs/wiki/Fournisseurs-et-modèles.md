# Fournisseurs et modèles

Chaque tâche a son fournisseur et son modèle. Le réglage par défaut est dans `config.toml` :

```toml
[tasks.transcribe]
provider = "mistral"
model = "voxtral-small-transcribe-3"
# provider = "elevenlabs"
# model = "scribe_v2"

[tasks.summarize]
provider = "mistral"
model = "mistral-large-latest"
```

Les tâches sont `context`, `vision`, `transcribe`, `identify`, `summarize` et `extract`. Pour passer la transcription sur ElevenLabs, commenter la paire Mistral et décommenter l'autre. Les options `--provider` et `--model` d'une commande l'emportent sur le fichier.

## Compatibilité

Un modèle n'est accepté que s'il a les capacités exigées par la tâche. Sinon la commande s'arrête et liste les modèles compatibles.

| Tâche | Capacités exigées |
|---|---|
| `context` | `chat`, `json_schema` |
| `vision` | `chat`, `json_schema`, `vision` |
| `transcribe` | `stt`, `diarization` |
| `identify` | `chat`, `json_schema` |
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

## Suivre sa consommation

Chaque appel payant est noté dans `runs/usage.jsonl` : fournisseur, modèle, jetons envoyés et reçus, secondes d'audio, coût indicatif. L'encart **Consommation API** de l'interface en fait les totaux du mois.

- **Mistral** n'a pas d'API de quota ni de solde. Le journal local est la seule source dans l'outil. Les limites de débit (jetons et requêtes par minute) sont lues sur les en-têtes des réponses. Les montants réels sont sur la [console Mistral](https://admin.mistral.ai/organization/usage).
- **ElevenLabs** donne les crédits consommés par produit (STT, TTS…) sur 30 jours. La limite de l'abonnement et sa date de remise à zéro ne s'affichent que si la clé a la permission `user_read`.

Les prix du texte Mistral sont dans `rpsum/usage.py` (`CHAT_PRICES`), ceux de la transcription dans chaque fournisseur (`stt_price_per_min`). Ce sont des prix indicatifs, à vérifier sur les pages tarifaires.

## Transcription : ElevenLabs ou Mistral

Sur les deux premières sessions d'essai, ElevenLabs a mieux séparé les voix et il est le seul à signaler les rires, utiles pour le bêtisier. Mistral est le choix par défaut pendant le développement. Les coûts sont voisins : environ 0,65 dollar pour une session de 2 h 50.

Avec Mistral, la session est découpée sur les silences. Des clips de référence, tirés du premier morceau, servent à garder les mêmes locuteurs d'un morceau à l'autre. La taille des morceaux se règle dans `config.toml` (`mistral_chunk_seconds`).

## Modèles locaux

Lancer Ollama ou `llama-server` sur la machine qui a le GPU, puis donner son adresse dans `.env`. Exemple :

```bash
OLLAMA_BASE_URL=http://192.168.1.20:11434
uv run rpsum models --task summarize
uv run rpsum summarize ma-session --provider ollama --model <modèle>
```
