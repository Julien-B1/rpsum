# Fichiers produits

Tout ce qui concerne une session se trouve dans `runs/<id>/`. Ce dossier n'est pas commité.

| Fichier | Étape | Contenu |
|---|---|---|
| `source.json` | `ingest` | titre, chaîne, durée, URL, chapitres |
| `audio.opus` | `ingest` | audio mono 16 kHz, environ 11 Mo par heure |
| `transcripts/<fournisseur>__<modèle>…/` | `transcribe` | `raw.json` (réponse brute), `transcript.json`, `transcript.md` |
| `transcript.json` | `transcribe`, `identify` | transcript courant, au format commun |
| `transcript.md` | `transcribe`, `identify` | version lisible, horodatée |
| `hints.json` | manuel | ce qu'on sait de la distribution |
| `vocab.txt` | manuel | noms propres, un par ligne |
| `cast.json` | `identify` | distribution, à relire et corriger |
| `scenes.json` | `summarize` | fiches de scène |
| `summary.<nom>.md` | `summarize` | un résumé par nom |
| `highlights.json`, `highlights.md` | `extract` | passages retenus |
| `clips/` | `extract --clips` | extraits audio |
| `run.json` | toutes | journal : fournisseur, modèle, durée et coût estimé de chaque étape |

## Format d'une réplique

```json
{
  "id": 162, "start": 1298.4, "end": 1300.1,
  "speaker": "speaker_0",
  "text": "Vous êtes qui, vous ?",
  "events": [],
  "player": "Kratos", "role": "mj",
  "character": "le vieux pêcheur", "mode": "en-jeu"
}
```

`speaker` vient de la transcription. `player`, `role`, `character` et `mode` viennent de `identify`. Une `confidence` de 0,3 signale une réplique attribuée au MJ qui vient probablement d'un joueur.
