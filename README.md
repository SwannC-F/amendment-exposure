# Exposition — les amendements qui vont être votés, vus depuis votre entreprise

Hackathon Open Data swanbase × Hémicycle — 14/11/2026.

**Démo en ligne : https://swannc-f.github.io/amendment-exposure/** (touches 1–4 pour changer d'entreprise)

## Le problème

Un projet de loi a une étude d'impact. Un amendement n'en a pas. Sur la loi titres-restaurant, 34 amendements attendent la séance du Sénat du jeudi 19/11 : personne ne dit quelles entreprises chacun concerne, combien ça leur coûte ou leur rapporte, ni qui le porte.

## Ce que fait l'outil

Pour une entreprise (un SIREN), chaque mesure en attente devient une carte :

- **Pour vous** : gain ou perte estimée en €/an, en fourchette, chaque hypothèse citée.
- **Au total** : combien d'€ par an la mesure déplace, des perdants vers les gagnants.
- **Exposition** : nombre d'entreprises des secteurs visés et fourchette d'employés.
- **Soutien** : combien de groupes politiques portent la mesure, majorité sénatoriale incluse ou non.
- **Historique et alliés** : ce qui a déjà été tenté au Sénat, et les organisations qui ont déclaré à la HATVP une position alignée ou opposée à la vôtre.

Exemple : le plafonnement des commissions des émetteurs déplace 108 à 330 M€/an des émetteurs vers les commerces ; porté par 5 groupes dont l'Union centriste ; perte de 10,8 à 132 M€/an pour Edenred France, gain pour Hippopotamus.

## Comment c'est calculé

| Étape | Script | Source |
|---|---|---|
| Amendements en attente + groupe de l'auteur | `fetch_amendments.py` | Sénat : CSV des amendements, liste des sénateurs (data.senat.fr) |
| Entreprises visées (codes NAF), citation à l'appui | `extract_criteria.py` (LLM, Featherless) ; `build_criteria_142.py` (relu à la main pour la démo) | Texte des amendements |
| Soutien politique par mesure | `signals.py` | Groupes des auteurs |
| Entreprises et employés exposés | `exposure.py` | API Recherche d'entreprises (unités légales actives, tranches d'effectifs INSEE) |
| Chiffrage en €/an, par entreprise | `chiffrage_a.py`, `chiffrage_b.py` | Chiffres cités dans les amendements, Autorité de la concurrence, CA (API Recherche d'entreprises) |
| Historique | `history_ameli.py`, `history_hatvp.py`, `history_clair.py`, `history_legifrance.py` | Ameli (Sénat, depuis 2001), HATVP, CLAIR (votes), Légifrance (PISTE) |
| Profils et classement | `profiles.py` | Tout ce qui précède → `data/feed_142.json` |
| Page | `index.html` | Lit `data/` |

Relancer : `python3 fetch_amendments.py 142 && python3 build_criteria_142.py && python3 signals.py 142 && python3 exposure.py 142 && python3 profiles.py 142`, puis `python3 -m http.server`.

## Règles et limites

- Aucun chiffre inventé : chaque paramètre vient d'une citation ou d'une source nommée ; sinon la carte affiche « non chiffrable ».
- Toujours des fourchettes. Le soutien politique est un signal descriptif, pas une probabilité.
- Effectifs de toute l'entreprise, pas seulement de l'activité visée. Émetteurs et plateformes n'ont pas de code NAF propre : non comptés, signalés.
- Un seul texte préparé (Sénat). La suite est dans [ROADMAP.md](ROADMAP.md).
