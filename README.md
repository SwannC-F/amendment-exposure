# Exposition — les amendements qui vont être votés, vus depuis votre entreprise

Hackathon Open Data swanbase × Hémicycle — 14/11/2026.

**En ligne, avec le direct : https://amendment-exposure-eu.onrender.com** (serveur gratuit : la première visite le réveille, ~50 s).

## Le problème

Un projet de loi a une étude d'impact. Un amendement n'en a pas. Des dizaines d'amendements tombent sur un texte : personne ne dit quelles entreprises chacun concerne, combien ça leur coûte ou leur rapporte, ni qui le porte.

## Ce que fait l'outil

1. On choisit un texte du Sénat (session + numéro) et on cherche **n'importe quelle entreprise** (nom ou SIREN, Sirene en direct).
2. Pour chaque mesure en attente qui la vise : **gain ou perte en €/an** (fourchette, chaque paramètre cité mot pour mot), **entreprises et employés exposés**, **soutien politique** (groupes qui portent la mesure, majorité sénatoriale), **historique** (amendements passés, lois qui ont modifié les mêmes articles) et **alliés / adversaires** déclarés à la HATVP.
3. **En direct** : les amendements du Sénat récupérés à l'instant, un amendement lu par le modèle devant vous, l'analyse IA d'une entreprise qu'aucun code NAF ne relie au texte, et le recalcul complet d'un texte à la demande.

## Tout est recalculé par le code

Aucune donnée écrite à la main : une commande reconstruit tout pour n'importe quel texte.

```bash
python3 pipeline.py 2026-2027 142
```

| Étape | Script | Source |
|---|---|---|
| Amendements en attente, groupe de l'auteur | `fetch_amendments.py` | Sénat (CSV des amendements, liste des sénateurs) |
| Critères : secteurs (NAF), rôles, effet, citation vérifiée | `extract.py` (LLM) | Texte de chaque amendement |
| Regroupement en mesures (et mesures opposées) | `group.py` (LLM) | Critères |
| Soutien politique | `signals.py` | Groupes des auteurs |
| Entreprises et employés exposés | `exposure.py` | API Recherche d'entreprises |
| Chiffrage : assiette × écart × part du secteur | `chiffrage.py` (LLM + formule unique) | Chiffres cités dans les amendements du texte |
| Historique et lobbying | `history.py` | Légifrance (PISTE), Ameli (Sénat), HATVP |
| Fichier lu par la page | `engine.py` | Tout ce qui précède → `data/<session>/<texte>/engine.json` |

Le client LLM commun (`llm.py`) met les réponses en cache et vérifie chaque citation après normalisation typographique ; un paramètre dont la citation n'est pas retrouvée est écarté, et la mesure devient « non chiffrable » plutôt que d'afficher un chiffre inventé. Conception : [`.0-first-pass/2026-11-14-live-pipeline.md`](.0-first-pass/2026-11-14-live-pipeline.md).

## Lancer en local

```bash
cp .env.example .env    # LLM_API_KEY (Featherless), PISTE_CLIENT_ID / PISTE_CLIENT_SECRET (Légifrance)
python3 server.py       # page + API sur http://localhost:8766
```

Hébergement : `render.yaml` (Render, région Francfort : le site du Sénat ne répond pas depuis les États-Unis). Les secrets sont des variables d'environnement Render, jamais dans le dépôt.

## Règles et limites

- Aucun chiffre inventé ; toujours des fourchettes ; « exposition », jamais « impact ». Le soutien politique est un signal descriptif, pas une prévision du vote.
- Le chiffrage ne prend que les chiffres présents dans les amendements du texte : sans assiette ou écart cités, la mesure reste « non chiffrable ».
- Effectifs de toute l'entreprise, comptes d'entreprises approximatifs (« ≈ »). Seul l'auteur principal de chaque amendement est compté.
- La suite est dans [ROADMAP.md](ROADMAP.md).
