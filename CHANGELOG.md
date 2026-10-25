# Changelog

Les évolutions notables du projet sont notées ici, selon le format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque version correspond à une étape du projet et porte un tag Git (`v0.0`, `v0.1`, etc.).

## [Non publié]

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
