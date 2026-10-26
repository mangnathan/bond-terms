# ADR 0002 : lecture des scans, vérité terrain affinée et conception des extracteurs

- Statut : accepté
- Date : 26 octobre 2026
- Version : v0.2

## Contexte

La v0.1 a figé le découpage et lu les 602 PDF. Deux questions restaient ouvertes avant d'écrire le moindre extracteur :

- 8 documents du test sont des scans sans texte. L'ADR 0001 compte une valeur refusée comme une erreur : un extracteur qui ne lit que le texte serait limité à environ 95 % sur ces champs, sous les seuils de 98 %.
- La vérité terrain vient de FIRDS. Rien ne garantit que chaque valeur de FIRDS figure dans le document rattaché par le registre. Une valeur absente du document est une erreur que personne ne peut éviter.

Les deux questions ont été mesurées sur le seul jeu de développement, avec `scripts/adr0002/mesure_ocr.py`. Le texte des documents de test n'a pas été lu. Les sorties, sans aucun texte de document, sont dans `docs/v0.2-extraction/data/`.

## Mesures sur le développement

### OCR des scans

Les 10 scans du développement (89 pages) ont été lus par RapidOCR 3.10 (modèles PP-OCR fournis avec le paquet, moteur onnxruntime, sans réseau), après un rendu des pages à 200 points par pouce. Durée : 3,25 secondes par page en médiane, 4 minutes 53 pour les 10 documents, sur un poste à 8 Go de mémoire.

Pour savoir si l'OCR lit assez bien, on cherche dans son texte les valeurs de FIRDS (ISIN, échéance, devise, taux fixe, valeur nominale, montant), avec les fonctions testées de `bond_terms.valeurs` :

| Valeur de FIRDS retrouvée | Texte des PDF lisibles (342 couples) | OCR des scans (10 couples) |
|---|---|---|
| ISIN | 332 (97,1 %) | 9 (90 %) |
| Échéance | 325 (95,0 %) | 9 (90 %) |
| Taux fixe | 284 sur 294 (96,6 %) | 9 sur 9 |
| Valeur nominale | 338 (98,8 %) | 9 (90 %) |
| Montant comparable | 286 sur 326 (87,7 %) | 6 sur 6 |

Les trois manques de l'OCR viennent d'un seul document : une lettre de confirmation d'un agent placeur, rattachée à l'ISIN par le registre, qui ne contient ni ISIN ni date d'échéance complète. L'OCR lit donc les scans aussi bien que le texte natif.

### Valeurs de FIRDS absentes des documents

Les manques du texte natif ont été examinés un par un. Ils ne viennent pas de la recherche mais des données :

- **Rattachement erroné.** 11 couples sur 352 (3,1 %) associent un document à un ISIN qu'il ne cite pas : le document porte sur une autre obligation du même émetteur. 9 des 10 taux introuvables viennent de ces couples. Une fois ces couples écartés, le taux fixe est présent dans 99,7 % des cas et la valeur nominale dans 99,7 %.
- **Montant.** FIRDS publie l'encours actuel ; le document donne le montant de son émission. Après un abondement absent du registre, ou pour les obligations destinées aux particuliers, dont le prospectus n'annonce qu'un montant « estimé », les deux diffèrent. Même après exclusion des rattachements erronés, le montant n'est présent que dans 89,7 % des cas (93,3 % pour les conditions définitives seules).
- **Obligations perpétuelles.** FIRDS leur donne l'échéance conventionnelle du 31 décembre 9999 ; le document écrit « no fixed maturity date ». 5 des 8 échéances manquantes restantes sont dans ce cas.
- **Écarts réels.** Une échéance diffère entre FIRDS (8 août 2028) et le document (28 juillet 2028), et un titre nommé « Float » est décrit comme à taux fixe dans FIRDS. Ces cas relèvent du rapport d'exceptions de la v0.3.

## Décisions

### 1. Les pages sans texte sont lues par OCR

Toute page sans texte est lue par RapidOCR, en local, et son texte est mis en cache hors du dépôt. Les citations des valeurs extraites sont vérifiées dans ce texte, comme pour une page native. Les seuils de l'ADR 0001 ne changent pas.

### 2. Un couple document-ISIN n'entre dans la vérité terrain que si le document cite l'ISIN

Le contrôle est automatique et porte sur l'identifiant, jamais sur les valeurs à extraire. Il est appliqué de la même façon aux trois jeux avant toute extraction ; pour les deux jeux de test, seuls les comptes sont publiés. Les couples écartés sont listés comme anomalies de rattachement du registre et ne comptent pas dans l'exactitude.

### 3. Le montant reste mesuré, sans seuil de réussite

FIRDS ne donne pas la même grandeur que le document : l'écart n'est pas une erreur d'extraction, et le plafond mesuré (89,7 %) rend le seuil de 95 % inatteignable par construction. Le montant est mesuré et publié avec son intervalle, à titre indicatif, et chaque écart est examiné dans le rapport d'exceptions. Les seuils des autres champs ne changent pas.

### 4. « Perpétuelle » est une valeur d'échéance

Pour une obligation sans échéance, la bonne réponse est « perpétuelle », comparée à l'échéance du 31 décembre 9999 de FIRDS.

### 5. Deux extracteurs, une même sortie

- Sortie commune, décrite par un schéma JSON : pour chaque champ, la valeur, la citation exacte et la page, ou « absent ». Une valeur sans citation retrouvée par le code est refusée.
- L'extracteur à règles lit les rubriques numérotées des conditions définitives (« Maturity Date », « Rate of Interest », « Specified Denomination », en anglais et en français). Il sert de référence et de solution de secours.
- L'extracteur LLM reçoit les instructions et le schéma en tête, puis le document : ce préfixe stable profite de la mise en cache. Température 0, prompt versionné dans le dépôt, version du prompt et du modèle enregistrées avec chaque résultat.
- Les cas de régression viennent des erreurs observées : le prix d'émission pris pour le montant, le taux révisable dont le taux initial est écrit plus loin, l'obligation perpétuelle, le texte espacé (« 1 2 july »), le prospectus pour particuliers sans jour d'échéance, le document qui ne cite pas l'ISIN.

### 6. Modèle et coût nul

Le modèle est pris dans l'offre gratuite de l'API Gemini (vérifiée le 26 octobre 2026) : `gemini-3.8-flash` (mise en cache gratuite) comparé à `gemini-3.5-flash-lite`, plus léger. Le choix entre les deux se fait sur le tableau de compromis du développement (décision 7). Les plafonds par jour ne sont affichés que dans AI Studio : ils sont relevés le jour de la première requête. Règles :

- aucune facturation liée au projet Google de la clé, clé dans `.env` ;
- plafond local de requêtes par jour, fixé sous le plafond relevé dans AI Studio ;
- réponses mises en cache : un document n'est jamais envoyé deux fois avec le même prompt ;
- arrêt au premier refus pour quota, puis bascule sur l'extracteur à règles, signalée dans le résultat ;
- faux modèle dans la CI.

En offre gratuite, Google peut utiliser les données envoyées pour améliorer ses produits : seuls des documents publics de l'ESMA sont envoyés.

### 7. Un tableau de compromis

Sur le développement, chaque extracteur est décrit par son exactitude, sa latence par document (médiane et 95e centile), ses jetons par document et son coût. Le choix suit la règle de l'ADR 0001 : le LLM n'est retenu que s'il bat les règles d'au moins 2 points, borne basse de l'intervalle au-dessus de zéro.

## Alternatives écartées

- **Baisser les seuils pour tenir compte des scans** : la mesure montre que l'OCR les lit ; baisser les seuils aurait affaibli l'évaluation sans nécessité.
- **Tesseract** : demande une installation système sous Windows, hors de `uv`.
- **OCR en ligne ou lecture des images par le LLM** : coût ou quota, et dépendance au réseau pour une étape que le poste fait seul en 5 minutes.
- **Garder les couples mal rattachés** : ils comparent le document aux valeurs d'une autre obligation et mesurent le registre, pas l'extracteur.
- **Garder le seuil de 95 % sur le montant** : il mesurerait l'écart entre deux grandeurs différentes.

## Conséquences

- Le groupe de dépendances `ocr` (RapidOCR, onnxruntime, pypdfium2) rejoint la chaîne de lecture des PDF.
- La table `verite_terrain` gagne une colonne « ISIN cité dans le document », et les comptes d'anomalies de rattachement sont publiés pour les trois jeux.
- Ces décisions sont prises sur le développement, avant toute extraction. Le test n'est ouvert qu'une fois les extracteurs figés.

## Conventions de comparaison précisées pendant le développement de l'extracteur à règles

Ajoutées le 26 octobre 2026. Elles ont été mesurées sur le seul développement, avant l'écriture de l'extracteur LLM et avant toute ouverture des tests. Elles sont codées dans `bond_terms.comparaison`.

- **Rang « senior non préférée ».** Quand le document indique « Senior Non Preferred », FIRDS déclare SBOD dans 33 cas et SNDB dans 11 cas : les déclarants ne classent pas cette catégorie intermédiaire de la même façon. Une lecture « senior non préférée » est juste si FIRDS indique SNDB ou SBOD. Une lecture « senior » n'est juste que pour SNDB, une lecture « subordonnée » que pour SBOD ou JUND.
- **Yuan offshore.** Le document écrit CNH ; FIRDS, qui suit la norme ISO 4217, déclare CNY. Les deux sont équivalents.
- **Taux fixe puis variable, ou révisable.** FIRDS code ces titres tantôt en taux fixe, tantôt en taux variable : 31 contre 6 pour « fixed/floating », 4 contre 3 pour « resettable » sur le développement. La règle de comparaison ne change pas ; les extracteurs suivent la convention majoritaire (taux fixe, avec le taux initial) et les cas minoritaires restent comptés faux. Le rapport les signale comme une incohérence de FIRDS.
