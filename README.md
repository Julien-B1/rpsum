# rpsum

POC de résumé de parties de jeu de rôle enregistrées. À partir d'une vidéo YouTube ou d'un replay Twitch :

1. `ingest` — extrait l'audio.
2. `transcribe` — transcrit et sépare les voix (ElevenLabs, Mistral).
3. `identify` — retrouve MJ, joueurs et personnages, puis annote chaque réplique (en jeu, hors jeu, narration, règles).
4. `summarize` — résume selon un ton, une longueur et un format.
5. `extract` — sort moments forts, bêtisier et mèmes, avec citations vérifiées.

Chaque tâche choisit son fournisseur et son modèle (`config.toml`). Fournisseurs : Mistral, ElevenLabs, Ollama, llama.cpp.

```bash
uv sync
cp .env.example .env   # puis renseigner les clés
uv run rpsum doctor
uv run rpsum ingest "https://www.youtube.com/watch?v=..." --id ma-session
uv run rpsum transcribe ma-session --speakers 5
uv run rpsum identify ma-session
uv run rpsum summarize ma-session --preset chronique
uv run rpsum extract ma-session --clips
```

Mode d'emploi complet : voir le wiki du dépôt. Plan, résultats d'essais et backlog : `PLAN.md`.
