# Ressources (Discord #données-publiques, 14/11)

## Utile maintenant

- **API Recherche d'entreprises** : https://recherche-entreprises.api.gouv.fr/docs/ — étape 3, compter les entreprises par code NAF (et région, tranche d'effectifs).
- **CLAIR** (clair.vote) : API publique gratuite, sans clé, https://api.clair.vote/docs — amendements, votes, dossiers, **agenda**, lobbying, rapprochés par identifiants officiels.
  - Peut combler notre trou : **cosignataires** des amendements (le CSV du Sénat ne donne que l'auteur principal) → signal « porté par N groupes » plus juste. À vérifier dans la doc.
  - Limite : 10 requêtes/min, User-Agent obligatoire qui décrit le projet (mettre un nom générique, pas d'email perso).
  - Code AGPL-3.0 : https://github.com/accelaire/clair
- **HATVP open data** (représentants d'intérêts) : https://www.hatvp.fr/open-data-repertoire/ — bonus lobbying (aussi dans Hémicycle, jeu `representants_interets`).

## Plus tard (vision / suite)

- Hémicycle : bibliothèque https://hemicycle.ai/bibliotheque, docs https://hemicycle.ai/docs, guide https://hemicycle.ai/construire
- data.gouv.fr + son serveur MCP `https://mcp.data.gouv.fr/mcp`
- Assemblée https://data.assemblee-nationale.fr/, Sénat https://data.senat.fr/
- Légifrance / Judilibre via PISTE https://piste.gouv.fr/ ; EUR-Lex ; Parlement européen https://data.europarl.europa.eu/fr
- Sirene (Insee) https://portail-api.insee.fr/ ; BODACC ; commande publique (DECP)
- Territoires : API Géo, API Adresse, DVF, Géorisques, comptes des collectivités (OFGL)
- Économie / énergie : Insee BDM, Eurostat, Webstat (Banque de France), prix des carburants, ODRÉ, Météo-France, OpenFisca
