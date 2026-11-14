# Roadmap — Exposition

**Le problème :** un projet de loi a une étude d'impact, un amendement n'en a pas. Des dizaines d'amendements tombent sur un texte, et personne ne dit quelles entreprises chacun concerne, ni combien.

**La promesse V1 :** pour un texte en cours, montrer à une entreprise les amendements pas encore votés qui la concernent, combien d'entreprises et d'employés sont exposés, et qui porte chaque mesure.

## V1 — ce qu'on montre aujourd'hui

| # | Fonctionnalité | Ce que ça apporte | Comment on le fait | État |
|---|---|---|---|---|
| 1 | **Fil des amendements à venir** | On regarde ce qui va être voté, pas ce qui l'a déjà été. | CSV des amendements du Sénat, publié en temps réel (`fetch_amendments.py`). On garde ceux dont le sort est vide ou « recevable ». Texte de démo : titres-restaurant (n°142), en séance le 19/11. | ✅ |
| 2 | **Critères ciblés par amendement** | Traduit un texte juridique en « qui est visé » : secteurs, seuils, régions. | Un LLM lit le dispositif et l'objet, renvoie des codes NAF et une **citation mot pour mot** comme preuve (`extract_criteria.py`, Featherless). Pour la démo, critères relus à la main (`build_criteria_142.py`), citations vérifiées automatiquement. | ✅ |
| 3 | **Exposition chiffrée** | Donne un ordre de grandeur : combien d'entreprises, combien d'employés. | API Recherche d'entreprises : nombre d'unités légales actives par code NAF × tranche d'effectifs INSEE (`exposure.py`). Employés en **fourchette** (bornes des tranches). | ⏳ en cours |
| 4 | **Signal de soutien politique** | Indique quelles mesures ont des chances réelles, sans inventer de probabilité. | Groupe de chaque auteur (liste open data des sénateurs), mesures regroupées par thème : « porté par N groupes », et la majorité sénatoriale (LR, Union centriste) en fait-elle partie ? (`signals.py`) | ✅ |
| 5 | **Profils d'entreprise** | Le même texte, vu depuis *votre* entreprise : le top 5 change selon qui regarde. | Un profil = un SIREN → code NAF via l'API Recherche d'entreprises, plus un rôle pour les acteurs sans code NAF propre (émetteurs, plateformes). Une carte = une mesure, classée par soutien puis exposition (`profiles.py`). Démo : Hippopotamus, Carrefour Hypermarchés, Edenred, Uber Eats. | ✅ |
| 6 | **Interface de démo** | Une page lisible au projecteur, changement de profil en un clic (touches 1–4). | `index.html` statique, lit les fichiers de `data/`. Sources et précautions en pied de page. | ✅ |

**Règles de V1 :** « employés concernés » ou « exposition », jamais « impact » ni « emplois touchés » ; toujours des fourchettes et des sources ; le soutien est un signal descriptif, pas une probabilité.

## Limites connues de V1

- **Seulement l'auteur principal** de chaque amendement : sans les cosignataires, le soutien est sous-estimé.
- **Pas de sens gagnant/perdant** : une carte dit « concerné », pas « favorable » ou « défavorable ».
- **Effectifs de toute l'entreprise**, pas seulement ceux qui travaillent dans l'activité visée.
- **Acteurs sans code NAF propre** (émetteurs, plateformes) : pas comptés, signalés comme tels.
- **Un seul texte** préparé, le Sénat seulement.

## Après V1 — la suite

| Étape | Fonctionnalité | Comment |
|---|---|---|
| V1.1 | **Cosignataires** → signal de soutien plus juste | API CLAIR (api.clair.vote) ou fiches des amendements du Sénat. |
| V1.1 | **Gagnant / perdant par secteur** | Demander au LLM le sens de l'effet pour chaque secteur, avec citation. |
| V1.1 | **Assemblée nationale** + prédiction de vote | Amendements en attente via Hémicycle ; prédiction Orcet (Assemblée seulement). |
| V2 | **Tous les textes à l'ordre du jour**, mis à jour chaque jour | Ordre du jour du Sénat et de l'Assemblée, extraction automatique sur chaque nouvel amendement. |
| V2 | **Alertes** pour une entreprise suivie | « Un amendement déposé hier concerne votre secteur. » |
| V2 | **Lobbying** sur le sujet | Répertoire HATVP : qui a déclaré agir sur ce thème. |
| V3 | **Voir venir en amont** | Propositions de loi déposées, ordre du jour prévisionnel, questions écrites. |
