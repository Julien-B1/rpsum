# Interface

Une interface locale, dans le navigateur, couvre tout le parcours sans ligne de commande.

```bash
uv run streamlit run app.py
```

Elle s'ouvre sur `http://localhost:8501`.

## Barre latérale

- **Session** : choisir un run existant.
- **Nouvelle session** : URL ou fichier, identifiant, contexte de campagne collé dans la zone de texte, résumés à produire. Le bouton lance le pipeline complet.
- **Consommation API** : ce que rpsum a consommé ce mois-ci, et l'état des comptes. Détail dans [[Fournisseurs et modèles|Fournisseurs-et-modèles#suivre-sa-consommation]].

Un traitement en cours s'affiche en haut de page, avec son journal. La page se met à jour seule.

## Onglets

| Onglet | Contenu |
|---|---|
| Résumés | lire et télécharger les résumés. Formulaire pour en générer un autre : préréglage, ton, longueur, format, point de vue, périmètre, consigne, modèle. |
| Passages | moments forts, bêtisier, mèmes. Filtre par catégorie et note. Lecture de l'extrait audio et lien horodaté vers la vidéo. |
| Transcript | tableau filtrable par personne et par mode, recherche dans le texte. Un ⚠ marque les répliques douteuses. |
| Distribution | corriger qui est qui, puis réannoter le transcript. |
| Contexte | fiche de contexte, image lue à l'écran, édition du fichier de contexte. |
| Pipeline | relancer depuis une étape, réglages par défaut, journal des étapes avec durées et coûts estimés. |

## Fonctionnement

L'interface ne calcule rien elle-même. Chaque bouton lance une commande `rpsum` en tâche de fond et écrit son journal dans `runs/<id>/ui.log`. Fermer le navigateur n'arrête pas le traitement.

Les listes de modèles ne proposent que ceux qui conviennent à la tâche, chez les fournisseurs joignables.
