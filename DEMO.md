# Démo live — Exposition (3 minutes)

Site : https://amendment-exposure-eu.onrender.com · répété en ligne le 14/11/2026 à 16h40.

**Accroche (premières secondes, sans rien cliquer)**
> « Un projet de loi a une étude d'impact. Un amendement n'en a pas : en ce moment, 34 amendements sur les titres-restaurant attendent leur vote au Sénat, et personne ne dit aux entreprises lesquelles les visent. »

**Phrase de fin**
> « Chaque texte, chaque entreprise, avant le vote. Aujourd'hui 3 textes calculés de bout en bout, d'autres en route, demain tous les textes en discussion : le pipeline tourne seul, pour quelques centimes à quelques dollars par texte. »

## Le script

| Temps | Cliquer | Dire |
|---|---|---|
| 0:00–0:12 | Rien (onglet **Mon profil** déjà ouvert, champ vide) | L'accroche. « Exposition répond à une question : qu'est-ce qui se vote cette semaine pour ou contre mon entreprise ? » |
| 0:12–0:25 | Taper `Hippopotamus` (suggestions en 2–3 s) → cliquer la **2e ligne** : *HIPPO EXPLOITATION (HIPPOPOTAMUS)*, 1 000–1 999 salariés | « On part de votre SIREN, pas d'un mot-clé. Je suis Hippopotamus : Sirene en direct, code NAF, effectif, chiffre d'affaires publié, 77,4 M€. » |
| 0:25–0:30 | **Voir ce qui me vise →** | « 15 mesures dans 3 textes, Sénat et Assemblée. » |
| 0:30–0:55 | Faire défiler sous « Entreprises comparables » jusqu'à la carte **1 · Plafonner les commissions des émetteurs** | « Le plafond à 2,5 % des commissions : pour Hippopotamus, un gain de 116 à 348 k€ par an. Une seule carte relie tout : 5 groupes la portent, dont l'Union centriste, de la majorité sénatoriale ; 2 amendements identiques rejetés en 2026 ; 10 alliés déclarés à la HATVP, les émetteurs contre. Et au-dessus, vos concurrents directs, Buffalo Grill compris. » |
| 0:55–1:05 | **+ détails** (sous la carte 1) | « Un chiffre seulement s'il est cité mot pour mot : ici "le titre représente 15 % du chiffre d'affaires des restaurants", amendement n°24. Sinon, on écrit "non chiffrable". » |
| 1:05–1:45 | **ouvrir le texte →** (carte 1) → **Sénat, en direct → Ouvrir** → cliquer **n°21 rect.** (Mme Delattre, RDSE) | « Ça, c'est le Sénat maintenant : 34 amendements en attente, lus sur senat.fr il y a une seconde. Je clique un amendement déposé hier : un modèle le lit, extrait les secteurs visés, et on compte les entreprises dans Sirene. » *(pendant l'attente, ~20 s)* « Le modèle doit recopier la phrase qui justifie sa réponse ; le code vérifie qu'elle existe dans l'amendement. » → montrer **✓ citation vérifiée mot pour mot** et « Cet amendement concerne HIPPO EXPLOITATION ». |
| 1:45–2:00 | Passer à la **2e fenêtre** (navigation privée) déjà ouverte sur l'Assemblée n°2864 | « Même code, autre chambre : la proposition de loi IA et contenus culturels, calculée de bout en bout, 39 mesures. Pour un éditeur de logiciels, 35 le visent. » |
| 2:00–2:28 | Revenir à la 1re fenêtre → onglet **Sénat** (liste des textes en discussion) | **Pourquoi nous.** « Pappers Politique, Contexte, Dixit, POLITICO Pro, FiscalNote, Quorum, Datapolitics font de la veille : vous choisissez des mots-clés, ils vous envoient des alertes et des résumés IA. Nous, on part de l'entreprise, SIREN, NAF, chiffre d'affaires, et on en déduit les amendements qui la visent, avec les entreprises et les salariés exposés, et des euros quand le texte le permet. Y compris ceux que vous n'auriez pas pensé à surveiller. » |
| 2:28–2:48 | Rester sur l'onglet **Sénat**, montrer un bouton « Analyser ce texte (≈ 0,01 $) » **sans cliquer** | « Hémicycle annonce un service d'exposition par SIREN ; son propre guide indique qu'il n'est pas encore ouvert, avec un niveau fort, moyen ou faible prévu. Notre démo est une brique qui fonctionne déjà, en euros et en entreprises comptées, et qui se branche sur leur API. Chaque texte en discussion se lance d'un clic, coût affiché. » |
| 2:48–3:00 | Rien | La phrase de fin. |

**Les 3 phrases à placer quoi qu'il arrive** (tirées de COMPETITION.md) :
1. « On part de votre SIREN, pas d'un mot-clé. » (0:12)
2. « Un chiffre seulement s'il est cité mot pour mot ; sinon, "non chiffrable". » (0:55)
3. « Une seule carte relie qui porte la mesure, si la majorité suit, ce qui a déjà été tenté, qui est pour ou contre, et vos concurrents. » (0:30)

Si le direct prend du retard, couper d'abord l'Assemblée (1:45–2:00), jamais le « pourquoi nous » ni la phrase Hémicycle.

## Si ça plante

| Étape | Symptôme | Repli |
|---|---|---|
| Ouverture du site | Page blanche ou chargement > 10 s (Render endormi) | Dire l'accroche pendant le chargement ; il faut ~50 s au réveil. D'où le réveil obligatoire avant de monter (voir plus bas). |
| Recherche « Hippopotamus » | Pas de suggestions (API Recherche d'entreprises lente) | Taper le SIREN `322566043`. Sinon, dans « ou seulement un code NAF », taper `56.10A` → **Utiliser ce code** : pas d'euros (pas de CA), mais toutes les mesures. |
| Mauvaise entreprise choisie | « HIPPOPOTAMUS PORTE DES LILAS » (1re ligne, NAF 00.00Z, non employeur) → aucune mesure | **changer** en haut à droite, prendre la 2e ligne. |
| Ce qui me vise | Carte vide ou erreur | Onglet **Sénat** → carte n°142 : même contenu par texte. |
| Sénat, en direct | « connexion… » qui dure, ou « cache du dépôt (Sénat injoignable) » | Dire : « senat.fr ne répond pas à l'hébergeur, on affiche la dernière copie, datée. » Continuer avec la carte 1 déjà vue. |
| Extraction live | Écran noir > 20 s | Parler (la phrase sur la citation vérifiée). Si rien à 40 s : « le modèle réfléchit, je vous montre le résultat déjà calculé » → cliquer **n°37** (pré-calculé aussi) ou revenir à la carte 1 et ses **détails** (même preuve : citation, amendement source). Ne jamais attendre en silence. |
| Extraction live | Erreur rouge (clé LLM, 502) | « Le fournisseur du modèle ne répond pas ; les 13 mesures du texte ont été extraites par le même modèle ce matin » → **+ détails** de la carte 1. |
| Assemblée | La 2e fenêtre a perdu son profil | Rester dans la 1re fenêtre : onglet **Assemblée nationale** → n°2864. Dire seulement « 39 mesures calculées sur ce texte » sans s'arrêter sur la carte affichée pour Hippopotamus. |
| Onglet Sénat | Liste vide | Dire le chiffre : « 24 textes en discussion au Sénat, 2 calculés ici, le reste se lance d'un clic, coût affiché. » |

**Ne jamais cliquer** « Recalculer ce texte » ni « Analyser ce texte » (payant, plusieurs minutes).

## Les 2 minutes avant de monter (à 17h50)

1. **Réveiller le serveur** : ouvrir https://amendment-exposure-eu.onrender.com/api/health (doit répondre `{"ok": true…}`). Si Render a redémarré, le cache des réponses du modèle est perdu : refaire l'étape 4.
2. **Fenêtre 1 (démo)** : site ouvert sur **Mon profil**, cliquer **Effacer le profil** pour que le champ soit vide, zoom navigateur à 110–125 % pour la salle.
3. **Fenêtre 2 (navigation privée)** : site → Mon profil → « ou seulement un code NAF » `62.01Z` → **Utiliser ce code** → onglet **Assemblée nationale** → n°2864. Laisser ouverte sur la page du texte, défilée en haut.
4. **Pré-chauffer le direct** (dans la fenêtre 2) : ouvrir le Sénat n°142 → Sénat, en direct → Ouvrir → cliquer **n°21 rect.** et **n°37**, attendre les deux résultats (jusqu'à 60 s chacun). La réponse du modèle est alors en cache : sur scène il ne reste que le comptage Sirene (~20 s). Puis revenir sur l'Assemblée n°2864 dans cette fenêtre.
5. Couper les notifications, brancher le chargeur, onglet « Mon profil » de la fenêtre 1 au premier plan.

## Questions probables du jury

| Question | Réponse en une ligne |
|---|---|
| D'où viennent vos euros ? Comment savoir qu'ils sont justes ? | Chiffre d'affaires publié × une part × un écart, et chaque paramètre est une citation d'un amendement vérifiée mot pour mot par le code ; c'est une fourchette, et sans citation on écrit « non chiffrable » (11 mesures sur 13 pour Hippopotamus). |
| Le modèle peut se tromper ? | Oui : c'est pour ça qu'il doit citer, que le code vérifie la citation, et que le sens (gagnant/perdant) est marqué « estimé par l'IA » ; le ciblage passe par le code NAF, qui est imprécis (une entreprise n'a qu'un NAF, parfois trompeur : Mistral AI est en 82.11Z). |
| Le soutien politique, c'est une prévision de vote ? | Non : c'est le nombre de groupes qui déposent la même mesure, en ne comptant que l'auteur principal, et si l'un d'eux est dans la majorité sénatoriale ; un signal descriptif. |
| Combien coûte un texte ? | Le coût est affiché avant de lancer : environ 1 centime pour un petit texte, 0,30 $ pour les titres-restaurant, 3 $ pour le budget de la Sécu (1 770 amendements) ; un amendement en direct ≈ 1 centime. |
| Vous êtes concurrents d'Hémicycle ? | Non, une brique au-dessus : leur exposition par SIREN n'est pas encore ouverte (l'API répond 501, sortie prévue en niveau fort/moyen/faible) ; nous ajoutons les euros sourcés et le comptage d'entreprises, et nous pouvons nous brancher sur leur API. |
| Pourquoi pas leur API ou leur MCP aujourd'hui ? | On l'a testé : les amendements Sénat y arrivent une fois par nuit (ce matin 5h18 UTC), or on veut ceux déposés il y a une heure ; et Sirene y exige un filtre par SIREN ou commune, donc pas de comptage national par NAF ; c'est le branchement naturel pour la suite (historique, Orcet pour l'Assemblée), pas le cœur aujourd'hui. |
| Quelle différence avec Pappers Politique ou Contexte ? | Eux répondent à « que se passe-t-il sur mes sujets ? » par mots-clés, alertes et résumés ; nous à « qu'est-ce qui vise mon entreprise, et combien ? », à partir du SIREN, sans avoir à savoir quoi surveiller. |
| Quelles sont vos limites ? | Couverture : 3 textes calculés de bout en bout (Sénat 142 et 168, Assemblée 2864), d'autres en cours par un lot automatique, quand les concurrents couvrent tout, les débats et souvent l'UE ; peu d'euros : 3 mesures chiffrées sur 64, parce qu'on refuse tout chiffre non cité ; pas d'alertes, pas de comptes ni d'équipe, pas de prédiction de vote ; hébergement gratuit qui s'endort. |

Bonus si on demande le modèle économique : une couche « exposition par entreprise » au-dessus des plateformes de données (Hémicycle, Pappers Politique), qui les complète plutôt que de les remplacer ; clients : fédérations professionnelles, cabinets d'affaires publiques, PME sans lobbyiste ; produit suivant : l'alerte « un amendement déposé ce matin vous vise ». Ce qui est défendable, c'est le moteur de ciblage et de chiffrage sourcé, pas l'écran de veille.

## Ce qu'il vaut mieux ne pas montrer (vu en répétition)

- Carte **2 · Créer un pôle public d'émission** (Ce qui me vise) : affiche « gain de 174 k€/an » alors que la mesure demande un rapport ; le chiffre vient de l'écart de commission d'une autre mesure. Ne pas l'ouvrir. Il gonfle aussi « Gains possibles 290 – 523 k€/an » en haut du texte 142 : citer plutôt la carte 1 (116 – 348 k€/an).
- Le profil **Mistral AI** : NAF Sirene 82.11Z, ne ressort que par le rôle Employeur sur les titres-restaurant ; utiliser le NAF 62.01Z.
- Avec Hippopotamus, les cartes 14 (IA à usage professionnel, Assemblée) et 15 (rapport sur la formation au tir des policiers) apparaissent par le seul rôle « Employeur » : ne pas défiler jusqu'en bas.
- « Comment on calcule : CA × part 0.15–0.15 (share) × écart 0.01–0.03 » et, dans les détails, « share : 0 part », « Écart … : 0 – 0 part » : ne pas zoomer dessus.
