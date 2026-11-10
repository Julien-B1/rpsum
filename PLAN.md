# rpsum — POC de résumé de parties de JDR enregistrées

Plan de première itération. État des lieux réalisé le 2026-11-10.

## 1. Verdict de faisabilité

Faisable. Les cinq fonctions demandées sont couvertes par des API existantes. Trois points demandent une validation par essai réel avant de s'engager (voir §9, « spikes »).

| Fonction | Faisabilité | Remarque principale |
|---|---|---|
| Extraction audio YouTube / Twitch | Bonne | `yt-dlp` + `ffmpeg`. Fragile côté YouTube (anti-bot), à surveiller. |
| Séparation des locuteurs (diarisation) | Bonne en API, lente en local | ElevenLabs et Mistral le font nativement. |
| Identification MJ / joueurs / personnages | Moyenne | Aucune API ne le fait. C'est une passe LLM sur le texte, à valider par l'utilisateur. |
| Transcript avec didascalies | Bonne pour les sons, partielle pour l'intonation | Seul ElevenLabs balise les sons (rires, etc.). L'intonation se déduit surtout du texte. |
| Résumé paramétrable | Bonne | Map-reduce sur le transcript. |
| Moments forts, bêtisier, mèmes | Bonne | Extraction LLM avec citations vérifiées et horodatage. |

### Limites à connaître dès maintenant

- **Parole superposée.** Une table de JDR se coupe la parole en permanence. Mistral indique que la parole superposée n'est pas gérée. C'est la première source d'erreurs attendue.
- **Un joueur, plusieurs voix.** La diarisation sépare des voix physiques. Le MJ qui joue cinq PNJ reste un seul locuteur, et c'est le LLM qui doit dire quel PNJ parle.
- **Le « local ».** Il tournera sur un PC distinct (RTX 5080 16 Go, i7-10700KF, 64 Go de RAM), indisponible pendant le début du développement. Les fournisseurs Ollama et llama.cpp sont codés et testés contre des réponses simulées, puis validés sur la machine réelle quand elle est joignable. Leur URL se règle dans `.env`. Avec 16 Go de VRAM : Whisper large-v3 et un LLM de 12 à 14 milliards de paramètres quantifié tiennent, mais pas en même temps qu'un gros contexte.
- **Intonation.** Aucun modèle de transcription testé ne renvoie l'émotion. Une passe optionnelle avec un modèle audio en chat (Voxtral Small) est possible sur des extraits ciblés, mais ce modèle reformule au lieu de citer.

## 2. Ce que j'ai vérifié

### Machine

- WSL2 Ubuntu, Intel Core Ultra 7 165H, 4 vCPU alloués, 19 Go de RAM, 851 Go libres.
- Pas de `nvidia-smi`. `/dev/dxg` présent (GPU intégré Intel Arc, peu exploitable pour l'inférence sous WSL).
- Présents : `ffmpeg` 8.0.1, `uv` 0.12, Python 3.14, Node 24, Docker, `git`. Variable `HF_TOKEN` déjà définie.
- Absents : `yt-dlp`, `deno`, Ollama, llama.cpp. Aucun serveur Ollama joignable sur `localhost:11434` ni sur l'hôte Windows.

### Mistral (docs lues le 2026-11-10)

- Transcription : `POST /v1/audio/transcriptions`, modèles `voxtral-mini-transcribe-3` et `voxtral-small-transcribe-3`.
- Diarisation : `diarize=true`, exige `timestamp_granularities=segment`. Pas d'horodatage au mot.
- Réponse : segments `{text, start, end, speaker_id}`.
- Clips de référence : jusqu'à 8 clips de 3 à 15 secondes pour nommer les locuteurs, 10 locuteurs au total. Utile pour garder les mêmes identifiants d'un morceau à l'autre.
- `context_bias` pour les noms propres (PJ, PNJ, lieux). Fenêtre de 65 536 tokens partagée entre audio et biais.
- Durée maximale par requête : absente de la doc actuelle. L'ancienne page annonçait 3 heures. À mesurer.
- Balisage des sons non verbaux : non documenté.
- Audio en chat : `voxtral-small-latest` accepte une partie `input_audio`. Durée maximale non documentée.
- Tarifs : 0,0035 $/min (Mini) et 0,004 $/min (Small).

### ElevenLabs (docs lues le 2026-11-10)

- Transcription : `POST /v1/speech-to-text`, modèle `scribe_v2`.
- Diarisation jusqu'à 32 locuteurs, `num_speakers` réglable.
- `tag_audio_events=true` : sons balisés sous forme de mots de type `audio_event` (rires, bruits de pas).
- Horodatage au mot ou au caractère. `keyterms` : jusqu'à 1000 termes, surcoût de 20 %.
- Jusqu'à 10 heures par requête. Taille maximale : 3 Go selon une page, 5 Go selon l'autre.
- `source_url` accepte directement une URL YouTube. À tester, cela peut servir de secours si `yt-dlp` est bloqué.
- Tarif : 0,22 $/heure d'après la page de tarifs API (vue via un résultat de recherche, pas lue directement).
- Pas d'API LLM texte trouvée. ElevenLabs ne sert donc qu'à la transcription.

### yt-dlp

- Depuis fin 2025, YouTube exige un runtime JavaScript externe. Deno est le choix recommandé.
- YouTube impose de plus en plus des jetons « PO token » liés à la vidéo. Un plugin fournisseur de jetons peut devenir nécessaire.
- Twitch : `yt-dlp` gère les VOD. Les VOD réservées aux abonnés demandent les cookies du compte.

### Non vérifié

- Capacités audio actuelles d'Ollama et de llama.cpp (transcription, diarisation). Hypothèse de travail : ils servent le texte, et la transcription locale passe par un serveur Whisper séparé.
- Identifiants exacts des modèles texte Mistral actuels. Le plan les lit dynamiquement via `GET /v1/models`.
- Forfait ElevenLabs minimal pour l'accès API à Scribe.

## 3. Ce dont j'ai besoin

### Comptes et clés

1. **Clé API Mistral** (La Plateforme, facturation activée). À placer dans `.env` : `MISTRAL_API_KEY`.
2. **Clé API ElevenLabs** avec la permission Speech to Text. `ELEVENLABS_API_KEY`.
3. **`HF_TOKEN`** : déjà présent. Il faudra accepter les conditions des modèles pyannote sur Hugging Face si on fait la diarisation locale.

### Autorisations hors du répertoire de travail

Tout le reste tient dans `/home/julien/rpsum` (venv `uv`, binaire `deno` local, données). Deux exceptions à valider :

1. **Images Docker** pour Ollama et le serveur Whisper local. Les volumes de modèles restent dans `./data/models`, mais les images vont dans le stockage Docker.
2. **Optionnel :** un Ollama sur l'hôte Windows ou une autre machine avec GPU, si disponible. Il me faut alors son URL.

### Matière de test

1. Une URL YouTube et une URL Twitch de sessions réelles, en français de préférence.
2. Pour l'une d'elles, la distribution réelle : qui est MJ, quels joueurs, quels personnages. C'est la vérité terrain pour mesurer l'identification.
3. Si YouTube bloque : un export de cookies du navigateur.

### Décisions attendues

- Interface : CLI seule, ou CLI plus interface web locale (proposition : les deux, la web en dernier jalon).
- Langue cible des sessions : français seulement, ou multilingue.

## 4. Stack retenue

- **Python 3.12** géré par `uv` (3.14 système évité : les roues binaires audio suivent avec retard).
- **Typer** pour la CLI, **Pydantic v2** pour les schémas, **httpx** pour les appels API.
- **yt-dlp** (dépendance Python) + **Deno** (binaire dans `./bin`) + **ffmpeg** système.
- **Streamlit** pour l'interface web locale du dernier jalon.
- **Stockage :** fichiers JSON par étape dans `runs/<id>/`. Pas de base de données en itération 1.
- **Local :** Ollama en conteneur Docker pour le texte, `faster-whisper` + `pyannote` pour la transcription et la diarisation locales.
- **Tests :** `pytest`, avec les réponses API enregistrées en fixtures.

## 5. Architecture

### Pipeline

```
URL ──> ingest ──> transcribe ──> identify ──> summarize
                                                     └──> extract (moments forts / bêtisier / mèmes)
```

Chaque étape lit l'artefact de la précédente et écrit le sien. Une étape déjà faite n'est pas rejouée, sauf avec `--force`. On peut donc changer de modèle pour le résumé sans repayer la transcription.

```
runs/<id>/
  source.json          métadonnées (titre, durée, chapitres, URL)
  audio.opus           audio normalisé mono 16 kHz
  chunks/              découpes éventuelles
  transcript.raw.json  sortie brute du fournisseur
  transcript.json      format commun
  cast.json            distribution (locuteur -> joueur, rôle, personnages)
  transcript.md        transcript lisible annoté
  summary.<preset>.md
  highlights.json
  run.json             config effective, modèles, durées, coûts
```

### Format commun de transcript

```json
{
  "segments": [{
    "id": 42, "start": 512.3, "end": 518.9,
    "speaker": "speaker_2",
    "text": "Je lance un jet de perception.",
    "events": ["rires"],
    "player": "Léa", "role": "joueur",
    "character": "Mira", "mode": "hors-jeu",
    "tone": "amusé", "confidence": 0.8
  }]
}
```

`mode` vaut `en-jeu`, `hors-jeu`, `narration`, `règles` ou `aparté`. Les champs à partir de `player` sont remplis par l'étape `identify`.

### Abstraction des fournisseurs

Un fournisseur déclare ses modèles et leurs capacités. Une tâche déclare les capacités qu'elle exige. L'interface ne propose que les modèles compatibles.

| Capacité | Mistral | ElevenLabs | Local |
|---|---|---|---|
| `stt` | voxtral-*-transcribe-3 | scribe_v2 | faster-whisper |
| `diarization` | oui | oui | pyannote |
| `audio_events` | non documenté | oui | non |
| `word_timestamps` | non | oui | oui |
| `chat` | oui | non | Ollama / llama.cpp |
| `json_schema` | oui | non | oui selon modèle |
| `audio_chat` | voxtral-small-latest | non | à vérifier |

| Tâche | Capacités exigées | Fournisseurs possibles |
|---|---|---|
| `transcribe` | `stt` + `diarization` | ElevenLabs, Mistral, local |
| `identify` | `chat` + `json_schema` | Mistral, local |
| `summarize` | `chat` | Mistral, local |
| `extract` | `chat` + `json_schema` | Mistral, local |

Les listes de modèles sont lues à l'exécution : `GET /v1/models` chez Mistral, `/api/tags` et `/api/show` chez Ollama, `/v1/models` chez llama.cpp. ElevenLabs : liste statique. Mistral, Ollama et llama.cpp partagent un même client de chat compatible OpenAI.

Configuration par tâche dans `config.toml`, surchargée en ligne de commande :

```toml
[tasks.transcribe]
provider = "elevenlabs"
model = "scribe_v2"

[tasks.summarize]
provider = "mistral"
model = "mistral-large-latest"

[tasks.extract]
provider = "ollama"
model = "qwen3:8b"
```

## 6. Détail des étapes

### 6.1 `ingest`

- `yt-dlp` en audio seul, avec métadonnées et chapitres.
- Conversion `ffmpeg` en Opus mono 16 kHz (environ 30 Mo pour 4 heures).
- Options `--start` et `--end` pour traiter un extrait.
- Entrée fichier local acceptée, ce qui contourne tout blocage de téléchargement.
- Secours YouTube : cookies, puis plugin PO token, puis `source_url` d'ElevenLabs.

### 6.2 `transcribe`

- **ElevenLabs :** une requête pour toute la session, `diarize`, `tag_audio_events`, `keyterms` issus du lexique de campagne.
- **Mistral :** découpe en morceaux sur les silences, avec recouvrement. Les clips de référence extraits du premier morceau gardent les mêmes identifiants de locuteurs dans les suivants. La taille des morceaux sera fixée par mesure.
- **Local :** `faster-whisper` puis `pyannote`, fusion par horodatage.
- Normalisation vers le format commun. Fusion des segments consécutifs d'un même locuteur.

### 6.3 `identify`

1. **Distribution.** Le LLM reçoit un échantillon de chaque locuteur (début de session, présentations, passages où l'on s'interpelle par son nom) et propose `cast.json` : locuteur → joueur, rôle, personnages joués, avec les indices cités.
2. **Validation.** L'utilisateur relit et corrige `cast.json`. Il peut aussi le fournir à l'avance. C'est le point où une erreur coûte le plus cher en aval, d'où la relecture humaine.
3. **Attribution par réplique.** Passe LLM par fenêtres glissantes : pour chaque segment, `mode` et `character`. Sortie contrainte par schéma JSON, identifiants de segments obligatoires.

### 6.4 `enrich` — abandonné

Étape retirée le 2026-11-10. Ce qu'elle devait apporter existe déjà : `identify` produit le transcript en forme de script, avec personnage et mode par réplique, et les sons d'ElevenLabs restent dans le texte (`[rire]`). L'intonation déduite du texte par un LLM aurait été une supposition coûteuse, sans usage en aval.

### 6.5 `summarize`

- **Map :** découpe par scènes (chapitres de la vidéo si présents, sinon détection par LLM), résumé factuel de chaque scène avec PNJ, lieux, objets, décisions, jets marquants.
- **Reduce :** rédaction finale à partir des fiches de scène.
- Paramètres : `--tone` (épique, humoristique, journal de bord, neutre…), `--length` (court, moyen, long, ou nombre de mots), `--format` (récit, liste à puces, fiche de campagne, article, message Discord), `--pov` (narrateur ou un personnage), `--scope` (en jeu seulement, ou avec le hors-jeu).
- Préréglages dans `presets/*.toml`, modifiables sans toucher au code.
- Les fiches de scène sont mises en cache : changer de ton ne relance que le reduce.

### 6.6 `extract`

- Trois catégories : moments forts (retournements, réussites et échecs critiques, scènes d'émotion), bêtisier (fous rires, lapsus, erreurs de règles, hors-jeu comique), mèmes (répliques cultes, blagues récurrentes, propositions de légende).
- Signaux : densité de rires, parole superposée, exclamations, vocabulaire de jets de dés.
- Chaque élément : titre, catégorie, début, fin, citation exacte, explication, score.
- **Garde-fou :** la citation doit se retrouver dans le transcript aux segments indiqués. Sinon l'élément est rejeté.
- Sorties : `highlights.json`, version Markdown avec liens horodatés (`?t=`), et option `--clips` qui découpe les extraits audio avec `ffmpeg`.

## 7. Interface

### CLI

```
rpsum run <url>                       pipeline complet
rpsum ingest|transcribe|identify|summarize|extract <run-id>
rpsum models [--task summarize]       modèles compatibles par tâche
rpsum cast <run-id>                   afficher / éditer la distribution
rpsum doctor                          vérifie clés, binaires, serveurs locaux
```

### Web (dernier jalon)

Une page Streamlit : URL, choix fournisseur et modèle par tâche (listes filtrées), réglages du résumé, suivi d'avancement, édition de la distribution, affichage du transcript, du résumé et des moments forts.

## 8. Coûts et durées estimés pour une session de 4 heures

| Poste | Estimation |
|---|---|
| Transcription ElevenLabs | environ 0,90 $ (1,05 $ avec `keyterms`) |
| Transcription Mistral | 0,84 $ (Mini) à 0,96 $ (Small) |
| Passes LLM Mistral | 400 000 à 600 000 tokens en entrée au total. Tarif à lire sur la page de prix. |
| Transcription locale sur ce CPU | plusieurs heures, non mesuré |
| LLM local sur ce CPU | petits modèles seulement, plusieurs heures pour la session entière |

Un transcript de 4 heures fait de l'ordre de 40 000 à 60 000 mots. `run.json` enregistre la consommation réelle de chaque étape.

## 9. Jalons

Les trois premiers essais (« spikes ») lèvent les inconnues avant d'écrire le reste.

| # | Jalon | Critère de fin |
|---|---|---|
| 0 | Socle : dépôt, `uv`, config, `.env`, `rpsum doctor` | `doctor` au vert |
| 1 | Spike ingest : une vidéo YouTube et une VOD Twitch | deux fichiers `audio.opus` valides |
| 2 | Spike transcription : mêmes 15 minutes chez ElevenLabs et Mistral | comparaison écrite : erreurs, locuteurs, sons, taille maximale de morceau Mistral |
| 3 | Spike local : Ollama + Whisper sur 5 minutes | débits mesurés, décision sur le périmètre du local |
| 4 | Abstraction fournisseurs + registre de capacités + `rpsum models` | une tâche refuse un modèle incompatible |
| 5 | `transcribe` complet, format commun, découpe Mistral | session entière transcrite par les deux API |
| 6 | `identify` + édition de la distribution | distribution correcte sur la session de référence |
| 7 | ~~`enrich`~~ | abandonné le 2026-11-10 |
| 8 | `summarize` + préréglages | trois résumés de tons et formats différents depuis un seul run |
| 9 | `extract` + vérification des citations + clips | aucune citation inventée dans la sortie |
| 10 | Interface Streamlit | pipeline complet lancé depuis le navigateur |
| 11 | Bilan : qualité, coûts, limites, suites | document de bilan |

## 10. Évaluation

- **Identification :** taux de segments bien attribués sur un extrait de 15 minutes annoté à la main.
- **Transcription :** relecture d'un extrait, compte des erreurs sur les noms propres avec et sans lexique.
- **Résumé :** chaque fait du résumé doit se rattacher à une fiche de scène. Relecture humaine sur la session de référence.
- **Moments forts :** taux de citations vérifiées, puis jugement humain sur les dix premiers.

## 11. Risques

| Risque | Parade |
|---|---|
| YouTube bloque le téléchargement | cookies, plugin PO token, `source_url` ElevenLabs, fichier local |
| Parole superposée, diarisation confuse | `num_speakers` fourni, clips de référence, comparaison des deux API au jalon 2 |
| Mauvaise attribution des personnages | distribution validée par l'utilisateur, score de confiance par segment |
| Noms propres massacrés | lexique de campagne (`keyterms`, `context_bias`), correction par LLM |
| Citations ou faits inventés | vérification des citations, résumé bâti sur les fiches de scène |
| Local trop lent | périmètre réduit aux extraits, ou Ollama distant avec GPU |
| Limites Mistral non documentées | mesurées au jalon 2 |
| Droits sur les contenus | usage sur des sessions dont on a l'accord ; le POC ne republie rien |

## 12. Hors périmètre de l'itération 1

- Transcription en direct pendant le stream.
- Découpe vidéo des extraits (audio seulement).
- Mémoire de campagne sur plusieurs sessions.
- Génération d'images de mèmes.
- Multi-utilisateur, authentification, déploiement.

## Sources

- https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-files
- https://docs.mistral.ai/studio/audio/speech-to-text/diarize-speakers
- https://docs.mistral.ai/studio/audio/audio-in-chat
- https://docs.mistral.ai/inference/pricing
- https://elevenlabs.io/docs/overview/capabilities/speech-to-text.md
- https://elevenlabs.io/docs/api-reference/speech-to-text/convert.md
- https://elevenlabs.io/pricing/api
- https://github.com/yt-dlp/yt-dlp/wiki/PO%20Token%20Guide

## Annexe — résultats des essais du 2026-11-10

Extrait testé : YouTube « Les larme de la sirène », 00:20:00 à 00:35:00. Fichiers dans `runs/yt/`.

- **Extraction :** YouTube (2 h 48) et Twitch (3 h 15) téléchargés en audio seul avec `yt-dlp[default]` et Deno local. Aucun cookie requis. Audio normalisé : environ 31 Mo par session.
- **ElevenLabs `scribe_v2` :** 22 s pour 15 min. 4 locuteurs, 13 événements sonores (`[rire]`, `[souffle]`…), horodatage au mot, texte verbatim avec hésitations.
- **Mistral `voxtral-small-transcribe-3` :** 34 s pour 15 min. 5 locuteurs trouvés pour 4 voix, attribution instable entre les joueurs. Texte nettoyé, sans hésitations ni sons. 11 625 tokens audio pour 900 s, soit environ 13 tokens par seconde : la fenêtre de 65 536 tokens impose des morceaux de 30 à 45 min.
- **Clé ElevenLabs :** limitée à la transcription (pas de lecture du compte). Suffisant.
- **Modèles texte Mistral disponibles :** `mistral-large-latest`, `mistral-medium-latest`, `mistral-small-latest` (262 144 tokens de contexte), lus via `GET /v1/models` avec leurs capacités.

### Sessions entières (2026-11-10)

| Session | Fournisseur | Durée audio | Temps de traitement | Locuteurs | Coût estimé |
|---|---|---|---|---|---|
| YouTube | ElevenLabs `scribe_v2` | 2 h 48 | 3 min 22 | 10 | 0,62 $ |
| YouTube | Mistral `voxtral-small-transcribe-3` | 2 h 48 | 9 min 10 (7 morceaux) | 8 | 0,67 $ |
| Twitch | ElevenLabs `scribe_v2` | 3 h 15 | 2 min 14 | 10 | 0,72 $ |

- Les deux fournisseurs trouvent plus de locuteurs que de personnes à table. Chez ElevenLabs, plusieurs identifiants cumulent moins d'une minute : à fusionner à l'étape `identify`, ou à éviter avec `--speakers N`.
- Mistral : les clips de référence passent par un champ de formulaire `speaker_references[nom]` par clip. Cette forme n'est pas dans la doc, elle a été trouvée par essai. Une chaîne JSON dans un champ unique est ignorée sans erreur.
- ElevenLabs balise 183 sons sur la session YouTube, dont 145 rires.

### Étape `identify` (2026-11-10)

- Relance ElevenLabs avec `--speakers 5` et lexique des noms : 5 locuteurs sur les deux sessions. Le lexique corrige les noms propres (« Érik » : 0 puis 20 occurrences ; « Ray'Ana » : 0 puis 27 ; « Volkhar » : 0 puis 24).
- Distribution proposée par `mistral-large-latest` : MJ et quatre personnages attribués sur les deux sessions, avec les indices cités. Non confrontée à une vérité terrain.
- Annotation par réplique : 1850 sur 1858 (YouTube) et 1439 sur 1446 (Twitch).
- Limite constatée : la séparation des voix attribue parfois une réplique de joueur au MJ. Ces répliques sont marquées `confidence: 0.3` quand le modèle y voit un personnage joueur.

## Backlog

- **Fichier de contexte de campagne** (format à définir) : noms de personnages, de PNJ, de lieux, d'objets et autres termes propres à l'univers. Il alimente le lexique de transcription (`keyterms`, `context_bias`) et les prompts d'identification, de résumé et d'extraction. Il remplace `vocab.txt` et `hints.json`.
- **Présentation en début de session** : chaque joueur se présente et présente son personnage. Ces passages servent d'ancrage pour identifier les voix sans ambiguïté (clips de référence chez Mistral, indices sûrs pour l'étape `identify`).
- Correction des répliques de joueur attribuées au MJ par la séparation des voix.
- Transcription locale (Whisper + pyannote) sur la machine à GPU, et essai réel d'Ollama et de llama.cpp.

### Étapes `summarize` et `extract` (2026-11-10)

- Fiches de scène : 50 scènes (YouTube), 28 (Twitch), mises en cache dans `scenes.json`. Changer de ton ne relance que la rédaction.
- Préréglages : `fiche`, `chronique`, `discord`, `journal`, `dark-fantasy`. Tout paramètre se surcharge en ligne de commande.
- Deux défauts trouvés et corrigés : longueur dépassée (jusqu'à quatre fois la consigne), et répliques inventées entre guillemets. Une passe de coupe et un contrôle des guillemets contre le transcript ont été ajoutés.
- Reste vrai : un ton humoristique enjolive des détails hors guillemets, et les noms propres varient d'une scène à l'autre (« Arkexa », « Arc Hexa ») tant que le fichier de contexte n'existe pas.
- Extraction : 51 passages retenus et 3 rejetés (YouTube), 28 retenus et 10 rejetés (Twitch). Un passage est rejeté quand sa citation est introuvable dans le transcript.
- Limite de débit Mistral atteinte avec 16 appels simultanés : nouvel essai automatique ajouté.

### Contexte, commande `run`, interface (2026-11-10, après-midi)

Session d'essai : « JDR - Dimension Void : La secte de l'IA », 2 h 29, run `void`.

- **Lecture de l'écran.** Trois images capturées à partir de `t=229s`. Le modèle de vision relève le MJ et les quatre couples pseudo / personnage. Premier essai : pseudo et personnage inversés. Corrigé en lui faisant déduire l'ordre de l'étiquette du MJ (« Maître du Jeu - Karu »). Résultat conforme à l'image.
- **Fiche de contexte.** Construite depuis l'écran et la description de la vidéo. Premier essai : le modèle avait réparti « deux nains, un oni et un chat » entre les personnages, à tort. Corrigé : une description ne contient que ce qui est dit de l'entrée elle-même.
- **Transcription Mistral** avec lexique de la fiche : 7 min 19 pour 2 h 29, 6 morceaux, 0,60 dollar estimé. 7 voix trouvées pour 5 personnes ; l'identification les rattache aux 5 participants de la fiche.
- **Noms.** 35 mots ramenés à l'orthographe de la fiche (« Gontran » vers « Gontrand », « Grimgar » vers « Grimar »).
- **Reprise vérifiée.** `rpsum run void` relancé : transcription et identification gardées, résumé et extraction refaits, 1 min 11. `--from identify` : 3 min 21, sans retranscrire.
- **Fausse piste notée.** Le PNJ commanditaire s'appelle vraiment Karu, comme le MJ. Une règle qui interdisait le pseudo du MJ comme nom de PNJ a été ajoutée puis retirée.
- **Interface Streamlit** (`app.py`) : testée sans navigateur sur un run vide et deux runs complets, et serveur réel démarré une fois. Non vérifiée à l'œil dans un navigateur.

Non testé : liens Google Docs réels, PDF et images joints au contexte (seuls les fichiers texte locaux sont couverts par un test), fournisseurs locaux.
