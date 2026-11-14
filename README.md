# Exposition aux amendements

Hackathon Open Data swanbase × Hémicycle — 14/11/2026.

**En une phrase :** pour chaque amendement qui va être voté, combien d'entreprises et d'employés sont concernés, et lesquels comptent pour *ton* entreprise.

## Chaîne

1. **Fil** : amendements du Sénat déposés, pas encore votés (CSV `https://www.senat.fr/amendements/2026-2027/<n>/jeu_complet_2026-2027_<n>.csv`). Texte de démo : titres-restaurant (n°142).
2. **Critères** : un LLM extrait secteurs NAF, seuils de taille, région — affichés, modifiables, ou « critères non trouvés ».
3. **Exposition** : nombre d'entreprises (API Recherche d'entreprises / SIRENE) + fourchette d'employés (tranches SIRENE, Urssaf par NAF).
4. **Profils** : 2–3 SIREN → fil reclassé.
5. **Interface** : une page, des cartes, un sélecteur de profil.

Bonus : lobbying HATVP, prédiction de vote Hémicycle (Orcet).

## Règles

- « Employés concernés » / « exposition », jamais « emplois touchés » / « impact ».
- Toujours des fourchettes, sources affichées.
- Rien de Jolt : ni code, ni clés, ni données.
