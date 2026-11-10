# Utilisation

Toutes les commandes se lancent depuis la racine du projet. Les résultats vont dans `runs/<id>/`.

## Tout d'un coup : `rpsum run`

```bash
uv run rpsum run "https://www.youtube.com/watch?v=XXXX" --id ma-session --context ma-campagne.md
```

La commande enchaîne extraction, contexte, transcription, identification, résumés et extraction des passages.

| Option | Effet |
|---|---|
| `--id` | identifiant du run |
| `--context fichier.md` | contexte de campagne, voir [[Contexte de campagne]] |
| `--preset nom` | résumé à produire, répétable. Défaut : `[run] presets` de `config.toml` |
| `--speakers N` | nombre de personnes à table. Défaut : celui de la fiche de contexte |
| `--force` | refait tout depuis la transcription |
| `--from étape` | refait à partir de `context`, `transcribe`, `identify` ou `summarize` |

### Reprise

Relancer `rpsum run` sur un run existant (`rpsum run ma-session`) ne refait pas ce qui existe :

| Étape | Relance simple | `--force` |
|---|---|---|
| Audio | gardé | gardé |
| Contexte | gardé si ses entrées n'ont pas changé | gardé si ses entrées n'ont pas changé |
| Transcription | gardée | refaite |
| Identification | gardée | refaite |
| Fiches de scène | gardées | refaites |
| Résumés | refaits | refaits |
| Extraction des passages | refaite | refaite |

Refaire une étape efface ce que les suivantes en avaient tiré. Chez Mistral, une transcription interrompue reprend au morceau où elle s'est arrêtée.

Les sections suivantes décrivent chaque étape, lançable séparément.

## 1. Extraire l'audio

```bash
uv run rpsum ingest "https://www.youtube.com/watch?v=XXXX" --id ma-session
uv run rpsum ingest "https://www.twitch.tv/videos/123456" --id ma-session
uv run rpsum ingest /chemin/vers/enregistrement.mp4 --id ma-session
```

Sans `--id`, l'identifiant est construit à partir de la plateforme et de l'identifiant de la vidéo. Seul l'audio est téléchargé.

## 2. Transcrire

```bash
uv run rpsum transcribe ma-session --speakers 5 --vocab runs/ma-session/vocab.txt
```

| Option | Effet |
|---|---|
| `--speakers N` | nombre de personnes à table. Évite qu'une même voix reçoive plusieurs identifiants. |
| `--vocab fichier` | noms propres, un par ligne. Défaut : les noms de la fiche de contexte. |
| `--provider`, `--model` | autre fournisseur que celui de `config.toml` |
| `--start`, `--end` | ne traite qu'un extrait, en secondes. Utile pour un essai rapide. |
| `--language` | langue de la session, `fr` par défaut |
| `--force` | refait la transcription même si elle existe |

Chaque combinaison fournisseur, modèle et options garde ses fichiers dans `runs/<id>/transcripts/`. La dernière transcription complète lancée devient `runs/<id>/transcript.json`, celle que lisent les étapes suivantes.

## 3. Identifier les participants

Les participants connus viennent de la fiche de contexte (voir [[Contexte de campagne]]). Sans fiche, un fichier `runs/<id>/hints.json` joue ce rôle :

```json
{"gm": "Kratos", "characters": ["Hécate", "Lysandre", "Nakia", "Érik"], "people": 5}
```

En deux temps :

```bash
uv run rpsum identify ma-session --cast-only   # propose la distribution et s'arrête
# relire et corriger runs/ma-session/cast.json
uv run rpsum identify ma-session               # annote chaque réplique
```

`cast.json` associe chaque identifiant de voix à une personne, un rôle (`mj`, `joueur`, `autre`) et ses personnages. Deux identifiants qui portent le même `player` sont traités comme la même personne. `--redo-cast` recalcule la distribution.

Après cette étape, chaque réplique porte un mode :

| Mode | Sens |
|---|---|
| `en-jeu` | la personne parle ou agit en tant que personnage (ou PNJ pour le MJ) |
| `narration` | le MJ décrit une scène ou le résultat d'une action |
| `regles` | jets de dés, points de vie, règles |
| `hors-jeu` | blagues, discussion de table, technique |

`runs/<id>/transcript.md` prend alors la forme d'un script :

```
[00:21:38] Kratos / le vieux pêcheur (en-jeu) — Vous êtes qui, vous ?
[00:21:40] Joueur de Érik / Érik (en-jeu) — Je suis là pour vous aider.
```

## 4. Résumer

```bash
uv run rpsum summarize ma-session --preset chronique
uv run rpsum summarize ma-session --tone "pince-sans-rire" --length 200 --format puces --name puces
```

Voir [[Résumés]].

## 5. Extraire les passages marquants

```bash
uv run rpsum extract ma-session --clips
```

Produit `highlights.md` (trois sections, avec liens horodatés vers la vidéo) et `highlights.json`. `--clips` découpe l'audio des passages notés 8 sur 10 et plus dans `runs/<id>/clips/`. `--force` relance l'analyse.

Chaque passage cite une réplique. Si cette citation n'existe pas dans le transcript, le passage est rejeté.

## Autres commandes

```bash
uv run rpsum doctor                    # état des binaires, clés et serveurs
uv run rpsum models                    # tous les modèles et leurs capacités
uv run rpsum models --task summarize   # modèles utilisables pour une tâche
uv run rpsum <commande> --help
```
