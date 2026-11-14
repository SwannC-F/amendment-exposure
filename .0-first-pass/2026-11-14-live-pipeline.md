# First pass — tout recalculable par le code, pour n'importe quel texte du Sénat

Date : 14/11/2026 · Branche : `live-pipeline` · Auteur : Swann (avec Claude)

## Décisions de clarification

| Question | Décision |
|---|---|
| « Aucune data en place » | **Hybride** : un pipeline unique recalcule tout de zéro par le code ; ses sorties servent de cache (page instantanée, GitHub Pages) ; le direct traite les nouveaux amendements et l'analyse d'une entreprise. |
| LLM | API compatible OpenAI (Featherless), configurée par `.env` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). Sans clé : mode `LLM_MOCK` pour le développement seulement, jamais pour produire `data/`. |
| Chiffrage | **LLM + formule générique**, paramètres extraits du texte avec citation vérifiée mot pour mot. |
| Périmètre | **Tout texte du Sénat** (numéro + session) ; titres-restaurant (n°142) devient un exemple. |

## Ce qui est écrit à la main aujourd'hui et disparaît

| Fichier | Contenu manuel | Remplacé par |
|---|---|---|
| `build_criteria_142.py` | critères, codes NAF, thèmes des 34 amendements | `extract.py` (LLM, par amendement) + `group.py` (LLM, regroupement en mesures) |
| `chiffrage_a.py`, `chiffrage_b.py` | formules et paramètres codés mesure par mesure | `chiffrage.py` (LLM extrait les paramètres, formule unique) |
| `build_engine.py` | `RATE_SCOPE`, `ROLE_SCOPE`, `EMPLOYER_THEMES` (4 profils de démo) | taux par secteur issus de `chiffrage.py`, rôles issus de `extract.py` |
| `history_ameli.py` | classement des amendements passés par thème | même prompt de regroupement, rattaché aux mesures du texte courant |
| `history_legifrance.py`, `history_hatvp.py` | articles L. 3262 et mots-clés « titres-restaurant » en dur | articles de code cités par les amendements (regex) ; mots-clés tirés du titre du texte |
| `profiles.py` | 4 SIREN en dur | supprimé : la page cherche n'importe quelle entreprise |

## Modèle de données

Tout est indexé par `(session, texte)`, par exemple `2026-2027/142`. Sorties dans `data/<session>/<texte>/`, entièrement générées et régénérables.

- **`amendments.json`** (inchangé) : numéro, article, auteur, groupe, date, sort, dispositif, objet, URL.
- **`criteria.json`** : par amendement `{criteria_found, effect, who, sectors: [{naf, label}], roles: [enum], regions, quote, quote_verified, model, prompt_hash}`. `roles` est une liste fermée : `employeurs`, `emetteurs`, `plateformes`, `associations`, `collectivites`, `etat`, `menages`. Le LLM peut proposer `autre:<libellé>`, affiché tel quel mais non apparié.
- **`measures.json`** : `[{key, theme, amendments: [...], opposes: key|null}]`. Un regroupement LLM unique sur la liste `{numéro, effect}` ; `opposes` relie deux mesures contraires (supprimer / rendre effectif).
- **`signals.json`**, **`exposure.json`** : logique actuelle, par mesure.
- **`chiffrage.json`** : par mesure
  ```
  {mechanism, winners: [{naf|role, label}], losers: [...],
   base:  {name, low, high, unit: "€/an", quote, amendment},
   delta: {name, low, high, unit: "part", quote, amendment},
   shares: [{nafs: [...], role, low, high, quote, amendment}],
   total_eur_per_year: base × delta | null,
   not_computable: raison | null}
  ```
  Formule unique : transfert total = assiette × écart ; pour une entreprise, € = CA × part du secteur × écart. **Un paramètre dont la citation n'est pas retrouvée mot pour mot dans un amendement du texte est écarté** ; s'il manque un paramètre, la mesure est « non chiffrable ».
- **`history.json`** : Ameli (amendements passés rattachés aux mesures), HATVP (organisations, camps), Légifrance (textes qui ont modifié les articles cités).
- **`engine.json`** : ce que la page lit, construit à partir de tout ce qui précède, sans aucune constante métier.

Cache LLM : `data/cache/llm/<sha256(model + prompt + entrée)>.json`, ignoré par git. Relancer sans changement ne rappelle pas le modèle.

**Client LLM commun (`llm.py`)** — ajouts validés après le premier essai réel (GLM-5.2, 14/11, 11 s et 0,005 $ par amendement) :
- **Vérification des citations après normalisation typographique** : apostrophes et guillemets courbes, espaces insécables et fines, tirets insécables, espaces multiples. Sans elle, une citation juste est rejetée (le modèle remplace ’ par ').
- **Budget de réponse ≥ 4 000 tokens** : GLM-5.2 raisonne avant de répondre ; avec un petit budget, `content` sort vide (`finish_reason: length`). Le client relance une fois avec un budget doublé dans ce cas.

## Architecture

```
pipeline.py <session> <texte>
  fetch → extract (LLM, ×N amendements, 4 en parallèle) → group (LLM, ×1)
        → signals → exposure (API Recherche d'entreprises, cache des comptages)
        → chiffrage (LLM, ×M mesures) → history (Ameli, HATVP, Légifrance, regroupement LLM)
        → engine
server.py
  GET  /api/text/<session>/<texte>        engine.json (recalcule si absent, ?refresh=1 force)
  GET  /api/live/amendments                amendements du Sénat maintenant, `known` = déjà dans criteria.json
  POST /api/live/extract (SSE)             un nouvel amendement, critères + rattachement à une mesure
  POST /api/live/scan (SSE)                analyse d'une entreprise sur tous les amendements
index.html
  choix du texte (numéro), recherche d'entreprise, calcul des cartes dans le navigateur ;
  rendu en texte (DOM + textContent), aucun innerHTML
```

**Mise en ligne du direct (décision 14/11, 14h30) : Render.** Un seul service web Render exécute `server.py`, qui sert la page ET l'API sur la même adresse (pas d'appel croisé entre domaines). Déploiement par `render.yaml` depuis le repo GitHub (branche `live-pipeline` jusqu'à la fusion, puis `main`). `server.py` écoute `0.0.0.0:$PORT` ; la page appelle l'API sur sa propre origine quand elle est servie par `server.py`, et affiche « direct indisponible » sur GitHub Pages. Secrets (`LLM_API_KEY`, `PISTE_CLIENT_ID`, `PISTE_CLIENT_SECRET`) en variables d'environnement Render, jamais dans le repo. Le disque Render est éphémère : les caches (`data/cache/`, comptages) se reconstruisent ; les sorties du pipeline versionnées dans le repo servent de point de départ. Limite connue : l'offre gratuite s'endort après 15 min sans visite (réveil ~50 s) — on la réveille avant la démo. Coût LLM borné par les 25 $ de crédits ; le recalcul complet d'un texte est déclenché à la demande, jamais par une simple visite.

**Passage à l'échelle.** Le coût est linéaire en nombre d'amendements : 34 pour les titres-restaurant, plusieurs milliers pour un projet de loi de finances. Le cache par empreinte et le parallélisme borné (4) gardent un texte moyen sous quelques minutes. Les comptages d'entreprises sont mis en cache par `(naf, tranche)` et partagés entre textes. Sur GitHub Pages, la page lit les fichiers générés ; le direct n'existe qu'avec `server.py`.

## Données de production

Pas de base de données. Les fichiers de `data/` deviennent des sorties générées : on les régénère par `pipeline.py`, on ne les édite jamais. **Migration** : remplacer les fichiers actuels de `2026-2027/142` par la sortie du pipeline. **Retour arrière** : `main` et la page en ligne restent sur la version actuelle tant que la branche n'est pas fusionnée (la fusion revient à Swann).

## Risques

1. **Qualité du LLM** (codes NAF, regroupement, paramètres). Atténuation : citation vérifiée mot pour mot pour chaque critère et chaque paramètre ; comparaison automatique avec la version actuelle de n°142 (`compare.py` : mesures retrouvées, NAF communs, totaux) avant de fusionner.
2. **Chiffrage moins fin** que les études manuelles (une seule formule, paramètres pris dans le texte seulement, pas de sources externes comme l'avis de l'Autorité de la concurrence). Assumé : « non chiffrable » plutôt qu'un chiffre inventé.
3. **Clé LLM** : sans clé, le pipeline ne peut pas produire `data/` ; la démo resterait sur `main`.
4. **Délai** : 3h45 avant le rendu ; si la branche n'est pas prête, on présente `main`.

**Revue senior** : le modèle de données change en profondeur (thèmes et chiffrage générés au lieu d'écrits). Revue proposée sur cette page avant le code ; reviewer : Swann.
