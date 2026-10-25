# ADR 0001 : sujet, population, vérité terrain et critères de succès

- Statut : accepté
- Date : 21 octobre 2026
- Version : v0.0

## Contexte

Le projet extrait les conditions des obligations (montant, échéance, taux, clauses) à partir des documents publiés dans le registre des prospectus de l'ESMA. L'utilisateur visé est l'équipe « référentiel titres » d'une banque ou d'une société de gestion, qui crée aujourd'hui ces fiches à la main ou achète les données à un fournisseur.

Ces règles sont écrites et versionnées avant toute extraction sur un document, pour que les seuils ne puissent pas être choisis après avoir vu les résultats. Les chiffres de faisabilité cités ici viennent des scripts de `scripts/feasibility` et de leurs sorties dans `docs/v0.0-cadrage/data`.

## Décisions

### Les obligations classiques, pas les produits structurés

Le registre compte 6,5 millions de documents déposés entre janvier et septembre 2026, presque tous des produits structurés allemands (certificats, warrants). Même chez les émetteurs français, environ 10 % des conditions définitives concernent une obligation classique. Le projet se limite aux obligations classiques, définies dans `bond_terms.instruments.is_plain_bond` : code CFI DB ou DT, et taux fixe compris entre 0 et 10 % ou taux variable indexé sur une vraie référence (ni FORMULA, ni OTHER, ni panier d'indices). Les produits structurés sont hors périmètre.

### Une collecte qui part de FIRDS

Un tirage au hasard dans le registre ne trouve presque rien d'utile. La collecte part donc des obligations en circulation dans FIRDS, puis cherche leurs documents par ISIN.

- Titres : obligations classiques à ISIN français de huit émetteurs couvrant la banque, l'assurance, le luxe et l'aviation : BNP Paribas, Société Générale, Crédit Agricole S.A., BPCE, AXA, LVMH, Kering et Air France-KLM. Hermès n'a aucune obligation dans FIRDS.
- Documents : conditions définitives et prospectus d'émission isolée qui citent l'ISIN, sans les suppléments.
- Volume attendu : 838 obligations, dont environ 60 % ont un document dans le registre, soit environ 500 documents.

### La vérité terrain est officielle, pas annotée

L'indicateur principal porte uniquement sur des champs dont la valeur est publiée par une source officielle :

| Champ | Source | Règle de comparaison |
|---|---|---|
| Devise | FIRDS | Égalité exacte |
| Date d'échéance | FIRDS | Égalité exacte |
| Type de taux (fixe ou variable) | FIRDS | Égalité exacte |
| Taux fixe | FIRDS | Égalité à 4 décimales |
| Référence et marge d'un taux variable | FIRDS | Même référence et même durée (Euribor 3 mois n'est pas Euribor 6 mois), marge égale en points de base |
| Valeur nominale par titre | FIRDS | Égalité exacte |
| Montant nominal total | FIRDS | Seulement pour les ISIN qui n'ont qu'un seul document |
| Rang de la dette | FIRDS | Seulement quand FIRDS le renseigne (25 % des titres) |
| LEI de l'émetteur | FIRDS, nom contrôlé par GLEIF | Égalité exacte |

La référence est la publication complète de FIRDS du 17 octobre 2026, figée pour toute la version. Le montant total n'est comparé que pour les titres à document unique : quand une émission est abondée, FIRDS affiche le nouveau total alors que le premier document indique le montant initial, et l'écart ne serait pas une erreur d'extraction.

Je ne suis pas spécialiste de la finance de marché. Une vérité terrain annotée par un seul non-spécialiste fausserait la mesure : l'annotation manuelle est donc limitée à des rubriques littérales (niveau B), et elle reste indicative.

### Niveau B : rubriques littérales, à titre indicatif

Environ 50 documents de développement sont annotés deux fois, à une semaine d'écart, pour mesurer la cohérence de l'annotation. Les rubriques sont choisies après lecture de trois documents de développement, parmi : remboursement au gré de l'émetteur (Issuer Call), remboursement au gré du porteur (Investor Put), remboursement « make-whole », affectation verte des fonds. Ce niveau n'a pas de seuil de réussite. Le LLM juge est abandonné, faute de vérité fiable pour le calibrer.

### Découpage dans le temps

Les documents sont triés par date d'approbation ; les 30 % les plus récents forment le jeu de test. La date de coupure est calculée à partir des seules métadonnées du registre et versionnée avant toute extraction. Le test n'est ouvert qu'une fois, pour la décision finale.

## Critères de succès

| Indicateur, mesuré sur le jeu de test | Seuil |
|---|---|
| Exactitude de l'échéance, de la devise, du type de taux et du taux fixe | Au moins 98 % pour chacun |
| Exactitude de la marge, de la valeur nominale, du montant (document unique) et du rang | Au moins 95 % pour chacun |
| Valeur extraite sans citation retrouvée dans le document par le code | Refusée et comptée comme une erreur |
| Documents envoyés en revue humaine | Au plus 30 % |
| Rapport d'exceptions FIRDS / document | Au moins 80 % de vrais écarts, sur un contrôle manuel de tous les écarts signalés (50 au plus) |
| Coût | 0 €, nombre d'appels au LLM estimé avant chaque lancement |

### Règles ou LLM

La référence est un extracteur à règles, fondé sur les rubriques numérotées des conditions définitives. Le LLM n'est retenu pour le niveau A que s'il dépasse les règles d'au moins 2 points d'exactitude globale, avec une borne basse de l'intervalle de confiance à 95 % (bootstrap par document) au-dessus de zéro. Sinon, les règles sont retenues et le LLM sert seulement au niveau B.

Les seuils de production (fraîcheur des données, détection des pannes et des changements de format) seront fixés en v0.4.

## Précisions apportées avant toute extraction

Ajoutées le 21 octobre 2026 après une relecture externe du dépôt, alors qu'aucune extraction n'avait encore été faite sur un document.

- **Lecture des seuils.** Chaque seuil se juge sur l'estimation ponctuelle ; l'intervalle de confiance à 95 % (bootstrap par document) est publié à côté. Avec environ 150 documents de test, une exactitude de 98 % est connue à environ 2,2 points près : exiger que la borne basse dépasse 98 % reviendrait à exiger presque aucune erreur. Si l'estimation atteint le seuil mais pas la borne basse, le rapport l'écrit : « seuil atteint, marge statistique insuffisante ».
- **Exactitude globale.** Pour la comparaison entre les règles et le LLM, l'exactitude globale est calculée sur toutes les paires (document, champ) qui ont une valeur dans FIRDS, chaque paire comptant une fois. Le bootstrap tire des documents entiers.
- **Documents chronométrés.** Les dix documents de la saisie chronométrée ont été approuvés en 2022 ou 2023. Ils devraient se trouver dans la partie développement, mais ce n'est certain qu'une fois la date de coupure calculée. Si l'un d'eux tombe dans le test, il en est retiré.
- **Lecture de FIRDS corrigée.** La première version des scripts ignorait les références de taux variable écrites sous forme de code (`<Indx>EURI</Indx>`) et la durée de la référence. Ces titres avaient une référence vide et étaient exclus à tort. Après correction, la population visée passe de 1 160 à 1 163 obligations ; les chiffres de `docs/v0.0-cadrage/data` ont été recalculés.
- **Règle « obligation classique » renforcée.** La saisie chronométrée a fait apparaître un titre au coupon de « 60 % payable in arrear », décrit dans FIRDS comme un taux variable de référence OTHER, sans durée ni marge. Dans la population visée, 85 titres avaient cette référence et 240 un « taux fixe » au-dessus de 10 % : des coupons cumulés de produits structurés, presque tous de Société Générale. La règle exclut désormais les références OTHER et les paniers d'indices, et les taux fixes au-dessus de 10 %, seuil tiré de la distribution mesurée. La population visée passe de 1 163 à 838 obligations, pour environ 500 documents attendus.

Ajoutées le 25 octobre 2026, après la collecte du registre et avant le calcul de la date de coupure, le téléchargement du moindre PDF et toute extraction.

- **Unité et règle du découpage.** Le découpage se fait par document d'émission (conditions définitives ou prospectus d'émission isolée). La date de coupure est la plus récente date d'approbation telle que les documents approuvés à cette date ou après représentent au moins 30 % des documents ; tous les documents d'une même date restent du même côté.
- **Second jeu de test : émetteurs jamais vus.** Les 8 émetteurs suivent un petit nombre de modèles de documents, et le test principal vient des mêmes émetteurs : il ne mesure pas la capacité à lire le document d'un émetteur inconnu, qui est pourtant le cas courant d'une équipe référentiel titres. Un second jeu de test est donc constitué : 300 obligations classiques à ISIN français tirées au hasard (graine 20261025) parmi celles des autres émetteurs de FIRDS, puis leurs documents d'émission, réduits par un second tirage (même graine) à 100 documents au plus. Ces documents ne sont jamais ouverts pendant le développement ; ils sont ouverts une seule fois, avec le test principal, et leurs résultats sont publiés à côté, avec les mêmes indicateurs. La règle de choix entre l'extracteur à règles et le LLM reste fondée sur le test principal, comme fixé ci-dessus.

## Alternatives écartées

| Option | Raison |
|---|---|
| Tirage au hasard dans le registre | Noyé par les produits structurés allemands |
| Annotation manuelle comme vérité principale | Annotateur unique non spécialiste |
| LLM juge pour noter les extractions | Aucune vérité fiable pour le calibrer |
| Obligations à ISIN « XS », « US » ou « CH » | Documents rarement présents dans le registre, ou approuvés hors de l'Union |

## Conséquences

- La v0.1 construit la collecte (FIRDS, registre, PDF) et calcule la date de coupure avant toute extraction.
- Le temps de saisie manuelle de dix documents approuvés en 2022 ou 2023 sert de référence au business case.
- Les PDF ne sont jamais versionnés : le dépôt garde seulement les identifiants et les liens. À partir de la v0.1, les requêtes vers l'ESMA sont limitées à une par seconde, avec un cache local.
