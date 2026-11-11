# Changelog

Les évolutions notables du projet sont notées ici, selon le format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque version correspond à une étape du projet et porte un tag Git (`v0.0`, `v0.1`, etc.).

## [Non publié]

### Ajouté
- Nouveau test de la v0.4 ouvert une seule fois : le LLM est juste sur 91,1 % des paires contre 67,1 % pour les règles ; exceptions vérifiées à la main, 63,0 % de vrais écarts.
- Instantané des conditions extraites (`bond_terms.instantane`) : pour chaque ISIN, valeurs, citations, statut de revue et exceptions, et indicateurs de surveillance par jeu.
- API en lecture seule (`bond_terms.api`, FastAPI) : ISIN vérifié avec sa clé de contrôle, nombre d'appels limité, instantané validé au démarrage.
- Collecte hebdomadaire (`bond_terms.collecte`, workflow planifié) : nouveaux documents du registre lus, extraits et comparés à FIRDS par les modèles dbt de l'entrepôt, instantané publié en release, bilan sur la branche `donnees`.
- Déploiement de l'API sur Render (`render.yaml`) : instantané téléchargé au démarrage depuis la dernière release (`bond_terms.publication`), adresse du client lue dans `True-Client-IP` et plafond global de 600 appels par minute.
- Surveillance et alertes (`bond_terms.surveillance`) : seuils de l'ADR 0004 jugés sur une fenêtre glissante d'au moins 20 documents, issue GitHub ouverte si un seuil est franchi, en cas d'arrêt pour quota ou d'échec du workflow.
- L'instantané garde la mémoire de la collecte (documents déjà examinés, bilans) ; `/v1/sante` donne la date de la dernière collecte.
- Routes de l'API versionnées sous `/v1`, versions de l'API et des extracteurs dans `/v1/sante`, une ligne de journal par appel sans adresse du client.

### Corrigé
- L'API ne démarrait plus sur Render : elle cherchait la dernière release par l'API de GitHub, limitée à 60 appels par heure et par adresse IP sans jeton. Elle télécharge désormais l'instantané de la release `en-service`, que la collecte remplace chaque semaine.
- Un document lu par les règles faute de LLM (quota, service indisponible) n'était plus jamais relu, et l'API ne le signalait pas : chaque fiche porte désormais son extracteur, et un tel document est relu la semaine suivante.
- La collecte reprenait l'instantané de départ au lieu du plus récent : les releases sont triées sur leur date de publication, et non sur celle du commit visé.

## [v0.3] - 2026-11-10

Bilan ([ADR 0003](docs/adr/0003-revue-et-exceptions.md)) : sur un nouveau test de 131 documents d'émetteurs jamais vus, ouvert une seule fois, le LLM est juste sur 92,2 % des paires document-champ contre 60,9 % pour les règles. Devise et valeur nominale atteignent leur seuil avec une marge statistique insuffisante. La file de revue prend 17,6 % des documents (plafond : 30 %). Le rapport d'exceptions compte 78,1 % de vrais écarts, sous le seuil de 80 %.

### Ajouté
- ADR 0003, décidée sur les jeux connus avant tout code, avec ses précisions et son gel datés d'avant l'ouverture du nouveau test.
- Nouveau jeu de test (`bond_terms.nouveau_test`) : émetteurs jamais vus, tiré et versionné avant tout téléchargement, tirage de la v0.1 rejoué pour l'exclure.
- Vérification v2 : citation en deux morceaux, guillemets et tirets sans valeur ignorés, signe d'un nombre vérifié.
- Type de taux « fixe puis variable » ; règles v2 et prompt v3 avec la seconde période des titres hybrides.
- Contrôle des produits structurés que FIRDS déclare comme des obligations classiques, versé dans l'entrepôt.
- File de revue humaine (`bond_terms.revue`) et rapport d'exceptions (`bond_terms.exceptions`), avec la fiche de vérification et le calcul de la part de vrais écarts.
- Le nouveau test rejoint l'entrepôt ; commande d'ouverture v0.3 avec répétition sur un jeu connu.
- Rapport de revue et d'exceptions en LaTeX et en PDF.

### Modifié
- Un document part en revue seulement si le LLM n'a pas justifié une valeur clé ; les désaccords avec les règles sont affichés au relecteur.
- Les sorties des extracteurs portent leur version dans leur nom ; l'évaluation accepte plusieurs jeux.
## [v0.2] - 2026-10-28

Bilan ([ADR 0002](docs/adr/0002-conception-extracteur.md)) : sur le test principal, ouvert une seule fois, le LLM (`gemini-3.5-flash-lite`) est juste sur 90,8 % des paires document-champ contre 83,3 % pour l'extracteur à règles, un écart de 7,5 points [3,9 ; 11,0] : il est retenu. Sur les émetteurs jamais vus, 93,1 % contre 61,5 %. La valeur nominale atteint son seuil, le rang avec une marge statistique insuffisante, les autres champs non.

### Ajouté
- ADR 0002, décidée sur le développement avant toute extraction : OCR des pages sans texte, rattachement document-ISIN vérifié, montant sans seuil, conventions de comparaison, choix du modèle, gel des extracteurs.
- OCR locale des pages sans texte (`bond_terms.ocr`, RapidOCR) et contrôle du rattachement (`bond_terms.rattachement`), versé dans l'entrepôt.
- Sortie commune des extracteurs avec citation vérifiée dans le document (`bond_terms.extraction`) et comparaison avec FIRDS (`bond_terms.comparaison`).
- Extracteur à règles (`bond_terms.regles`), en anglais et en français.
- Extracteur LLM (`bond_terms.llm`) : prompt versionné, sortie JSON imposée, plafonds de l'offre gratuite inscrits dans le code, cache, arrêt au premier refus pour quota avec repli sur les règles, reprise bornée des surcharges, délai maximal par requête.
- Évaluation (`bond_terms.evaluation`) : intervalles à 95 % par tirage de documents, écart apparié entre les extracteurs, 35 cas de régression.
- Ouverture unique des jeux de test (`bond_terms.ouverture`), avec registre daté écrit avant toute extraction.
- Analyse des erreurs sur le test, après ouverture (`scripts/v0.2`).
- Rapport d'extraction en LaTeX et en PDF.
- Test qui lance chaque commande du projet avec `--help`.

### Corrigé
- Le lecteur CSV de l'entrepôt devinait les types : « True » devenait « true », si bien que `rubrique_echeance` valait faux pour tous les documents du mart `documents`. Aucun chiffre publié n'en dépendait.
- La commande d'ouverture du test ne lançait pas sa fonction principale ; le premier lancement n'a rien ouvert.
## [v0.1] - 2026-10-25

Bilan : les données de développement et de test sont rassemblées et le découpage est figé avant toute extraction. 502 documents d'émission couvrent 486 des 838 obligations ; la coupure du 27 septembre 2024 laisse 351 documents au développement et 151 au test, plus 100 documents d'émetteurs jamais vus. Les 602 PDF sont lus ; les 8 scans du test devront être traités par OCR (ADR 0002, avant la v0.2).

### Ajouté
- Client des sites de l'ESMA et de GLEIF (`bond_terms.esma`) : une requête par seconde au plus, nouvelle tentative seulement sur une erreur du serveur ou du réseau, adresses limitées aux sites prévus, téléchargement atomique avec empreinte SHA-256.
- Collecte de FIRDS (`bond_terms.firds`) avec manifeste des fichiers et index Parquet.
- Population (`bond_terms.population`) et documents du registre par ISIN (`bond_terms.registre`), avec cache des réponses.
- Découpage dans le temps et second test d'émetteurs jamais vus (`bond_terms.decoupage`), règles ajoutées à l'ADR 0001 avant le calcul.
- Téléchargement des PDF et extraction du texte normalisé (`bond_terms.documents`), y compris les PDF chiffrés, avec un contrôle de lecture sans contenu des documents.
- Entrepôt de données dbt (`entrepot/`) : tables brutes chargées par `bond_terms.entrepot`, marts `population`, `documents` et `verite_terrain`, 26 contrôles, construction testée en CI sur des données fabriquées.
- Cible BigQuery (bac à sable, sans facturation) et chargeur `bond_terms.bigquery` plafonné, avec `.env.example`.
- Rapport de collecte en LaTeX et en PDF ; chiffres de la collecte dans `docs/v0.1-collecte/data/`.

### Modifié
- La lecture de FIRDS passe de 21 minutes à 2 minutes 22 secondes : la mesure de la mémoire (`tracemalloc`) ne tourne plus à chaque lecture. L'index produit est identique.
## [v0.0] - 2026-10-23

Bilan ([ADR 0001](docs/adr/0001-cadrage.md)) : le cadre de l'évaluation est fixé avant toute extraction. La population compte 838 obligations classiques de huit émetteurs (banque, assurance, luxe, aviation) ; la vérité terrain est officielle (FIRDS, GLEIF) ; une saisie manuelle chronométrée donne la référence humaine : 3 minutes par document et 82 % de champs justes.

### Ajouté
- Lecture en flux des fichiers de dette de FIRDS (`bond_terms.firds`), testée sur les trois formes de référence d'un taux variable, avec un contrôle des taux variables restés sans référence.
- Règle « obligation classique » (`bond_terms.instruments.is_plain_bond`), qui exclut les produits structurés : taux fixe nul ou supérieur à 10 %, référence FORMULA ou OTHER, panier d'indices.
- Scripts de faisabilité (`scripts/feasibility/`) : index de FIRDS, part d'obligations classiques par segment du registre, couverture des émetteurs (LEI contrôlés auprès de GLEIF), tirage et comparaison de la saisie chronométrée.
- Chiffres de faisabilité et résultats de la saisie dans `docs/v0.0-cadrage/data/`.
- ADR 0001 : population, vérité terrain, découpage dans le temps, seuils, règle de choix entre extracteur à règles et LLM, précisions apportées avant toute extraction.
- Rapport de cadrage en LaTeX et en PDF.
- Contrôles de qualité : ruff (avec les règles de sécurité), mypy strict, pytest, pre-commit, et CI GitHub Actions bloquante sur `main`.
- README avec les sources de données (ESMA, GLEIF) et licence MIT.

### Corrigé
- La lecture de FIRDS ignorait les références de taux variable écrites sous forme de code (`<Indx>EURI</Indx>`) : ces titres étaient exclus à tort. Signalé par une relecture externe du dépôt.
- La règle « obligation classique » laissait passer des produits structurés de Société Générale (référence OTHER, « taux fixes » de 46 % ou 60 %), découverts pendant la saisie chronométrée. Population ramenée de 1 163 à 838 obligations.
