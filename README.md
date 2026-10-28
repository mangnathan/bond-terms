# bond-terms

Extraction des conditions des obligations (montant, échéance, taux, clauses) à partir des documents publiés dans le registre des prospectus de l'ESMA, avec un contrôle sur la base de référence FIRDS.

L'utilisateur visé est l'équipe « référentiel titres » d'une banque ou d'une société de gestion, qui crée aujourd'hui ses fiches de titres à la main ou les achète à un fournisseur de données. Chaque valeur extraite sera accompagnée d'une citation exacte du document, vérifiée par le code ; les cas douteux iront en revue humaine, et un rapport signalera les écarts entre le document et FIRDS.

## Avancement

| Version | Contenu | État |
|---|---|---|
| v0.0 | Cadrage : population, vérité terrain, seuils fixés avant toute extraction, référence humaine | Terminé |
| v0.1 | Collecte (FIRDS, registre, PDF), date de coupure du test, entrepôt de données | Terminé |
| v0.2 | Extracteur à règles contre LLM sur les champs vérifiables, test ouvert une seule fois | Terminé |
| v0.3 | Clauses littérales, file de revue humaine, rapport d'exceptions | À venir |
| v0.4 | API, collecte planifiée, surveillance de la qualité des données | À venir |
| v1.0 | Démonstration publique, note de synthèse, business case mesuré | À venir |

## Résultats du cadrage (v0.0)

- **Population** : 838 obligations classiques à ISIN français, émises par BNP Paribas, Société Générale, Crédit Agricole S.A., BPCE, AXA, LVMH, Kering et Air France-KLM. Environ 500 documents attendus.
- **Vérité terrain officielle** : l'indicateur principal ne porte que sur des valeurs publiées par FIRDS et GLEIF, sans annotation manuelle.
- **Seuils** : au moins 98 % d'exactitude pour l'échéance, la devise, le type de taux et le taux fixe ; au moins 95 % pour la marge, la valeur nominale, le montant et le rang. Le LLM ne sera retenu que s'il bat un extracteur à règles d'au moins 2 points.
- **Référence humaine** : une saisie manuelle chronométrée prend 3 minutes par document en médiane, avec 82 % de champs justes (58 sur 71).
- **Deux corrections avant toute extraction** : lecture des références de taux variable de FIRDS, et exclusion des produits structurés qui se font passer pour des obligations (population ramenée de 1 163 à 838).

Détails : [rapport de cadrage (PDF)](docs/pdf/bond-terms_v0.0_Rapport-de-cadrage.pdf) et [ADR 0001](docs/adr/0001-cadrage.md).

## Résultats de la collecte (v0.1)

- **Documents** : 486 des 838 obligations ont un document d'émission dans le registre, soit 502 documents (475 conditions définitives, 28 prospectus autonomes), dont 41 en français.
- **Découpage figé avant toute extraction** : coupure au 27 septembre 2024, 351 documents de développement et 151 de test. Un second test de 100 documents porte sur des émetteurs jamais vus.
- **PDF** : les 602 documents sont lus. 24 sont des scans sans texte, dont 8 dans le test : ils limitent un extracteur qui ne lit que le texte à environ 95 %, sous les seuils de 98 %. La réponse (OCR local et gratuit) sera décidée dans l'ADR 0002, avant la v0.2.
- **Entrepôt de données** : un projet dbt construit la vérité terrain de la v0.2 avec 26 contrôles. Il tourne sur DuckDB (poste et CI) et sur le bac à sable BigQuery, avec des résultats identiques et aucune dépense.

Détails : [rapport de collecte (PDF)](docs/pdf/bond-terms_v0.1_Rapport-de-collecte.pdf).

## Résultats de l'extraction (v0.2)

- **Le LLM est retenu.** Sur le test principal (148 documents, ouvert une seule fois), `gemini-3.5-flash-lite` est juste sur 90,8 % des paires document-champ, contre 83,3 % pour l'extracteur à règles : écart de 7,5 points [3,9 ; 11,0], au-dessus des 2 points exigés.
- **Il généralise.** Sur 99 documents d'émetteurs jamais vus, 93,1 % contre 61,5 % pour les règles.
- **Seuils.** La valeur nominale atteint son seuil (98,6 %) ; le rang l'atteint avec une marge statistique insuffisante (97,4 %) ; devise et échéance restent à 97,3 % pour 98 % exigés.
- **Baisse expliquée.** 20 taux justes sont refusés par la vérification des citations sur une mise en page à deux colonnes, et FIRDS code désormais en taux variable les titres à taux fixe puis variable qu'il codait en taux fixe.
- **Coût nul.** 629 requêtes à l'offre gratuite de l'API Gemini, sous des plafonds inscrits dans le code ; chaque valeur est appuyée sur une citation retrouvée dans le document.

Détails : [rapport d'extraction (PDF)](docs/pdf/bond-terms_v0.2_Rapport-extraction.pdf) et [ADR 0002](docs/adr/0002-conception-extracteur.md).

## Structure du dépôt

```
src/bond_terms/       code du projet : collecte, découpage, entrepôt, OCR, extracteurs, évaluation
entrepot/             projet dbt : modèles, tests de données, profils DuckDB et BigQuery
scripts/feasibility/  scripts de l'étude de faisabilité et de la saisie chronométrée
scripts/adr0002/      mesure de l'OCR et de la présence des valeurs de FIRDS (ADR 0002)
scripts/v0.2/         analyse des erreurs sur le test, après son ouverture
scripts/docs/         compilation des rapports LaTeX
tests/                tests unitaires et construction de l'entrepôt sur des données fabriquées
docs/adr/             décisions d'architecture
docs/v0.0-cadrage/    rapport de cadrage et chiffres produits par les scripts
docs/v0.1-collecte/   rapport de collecte et chiffres produits par la collecte
docs/v0.2-extraction/ rapport d'extraction, résultats et registre d'ouverture du test
docs/pdf/             rapports compilés
```

## Reproduire

Prérequis : Python 3.12 et [uv](https://docs.astral.sh/uv/). Les rapports se compilent avec [Tectonic](https://tectonic-typesetting.github.io).

```bash
uv sync
uv run pytest

# Étude de faisabilité (les données téléchargées vont dans data/, jamais versionné)
uv run python scripts/feasibility/build_firds_debt_index.py --date 2026-10-17   # environ 20 minutes
uv run python scripts/feasibility/measure_register_match.py
uv run python scripts/feasibility/check_issuer_coverage.py
uv run python scripts/feasibility/compare_timing_to_firds.py

# Rapport de cadrage
uv run python scripts/docs/build_report_pdf.py docs/v0.0-cadrage/v0.0-rapport-de-cadrage.tex docs/pdf/bond-terms_v0.0_Rapport-de-cadrage.pdf

# Collecte (v0.1) : requêtes vers l'ESMA espacées d'une seconde et mises en cache
uv run python -m bond_terms.firds --date 2026-10-17                  # environ 3 minutes
uv run python -m bond_terms.registre --firds-date 2026-10-17         # environ 15 minutes
uv run python -m bond_terms.decoupage --firds-date 2026-10-17 --registre-date 2026-10-23
uv run python -m bond_terms.documents                                # environ 600 PDF

# Entrepôt de données sur DuckDB
uv run python -m bond_terms.entrepot --firds-date 2026-10-17 --registre-date 2026-10-23
uv run dbt build --project-dir entrepot --profiles-dir entrepot
```

### Extraction et évaluation (v0.2)

```bash
# OCR des pages sans texte, puis contrôle « le document cite l'ISIN »
uv run --group ocr python -m bond_terms.ocr                         # environ 300 pages
uv run python -m bond_terms.rattachement

# Extracteurs sur le développement, puis évaluation (aucune requête : tout sort du cache)
uv run python -m bond_terms.lancement --extracteur regles
uv run --group llm --env-file .env python -m bond_terms.lancement --extracteur llm --modele gemini-3.5-flash-lite
uv run python -m bond_terms.evaluation
```

L'extracteur LLM demande une clé de l'API Gemini, créée dans AI Studio sur un projet sans facturation liée, dans `.env` (voir `.env.example`). Les jeux de test ont été ouverts une seule fois, le 27 octobre 2026 ; la commande `bond_terms.ouverture` refuse une seconde ouverture.

Le découpage et ses chiffres sont versionnés dans `docs/v0.1-collecte/data` : relancer la collecte un autre jour donnerait un autre registre, mais ne doit pas remplacer le découpage figé.

### Bac à sable BigQuery (facultatif)

Le même entrepôt peut tourner sur le [bac à sable BigQuery](https://cloud.google.com/bigquery/docs/sandbox), sans moyen de paiement. Il faut un projet Google Cloud sans facturation liée et un compte de service (rôles « Éditeur de données BigQuery » et « Utilisateur de job BigQuery ») dont la clé est rangée hors du dépôt. Copier `.env.example` en `.env`, le remplir, puis :

```bash
uv run --group bigquery --env-file .env python -m bond_terms.bigquery
uv run --group bigquery --env-file .env dbt build --project-dir entrepot --profiles-dir entrepot --target bigquery
```

Le chargeur refuse d'envoyer plus de 20 Mo et s'arrête à la première erreur ; chaque requête dbt est plafonnée à 1 Go lu. Les tables du bac à sable expirent après 60 jours.

Le registre des prospectus évolue en continu : les totaux par segment peuvent varier de quelques dizaines de documents d'un jour à l'autre.

## Données

Le projet utilise uniquement des données publiques :

- **ESMA** (Autorité européenne des marchés financiers) : la base de référence des instruments financiers FIRDS et le registre des prospectus. Source : ESMA, reproduction autorisée avec mention de la source ([mentions légales](https://www.esma.europa.eu/legal-notice)). Le dépôt ne contient aucun document de l'ESMA : seulement des identifiants (ISIN, liens) et des chiffres calculés à partir de ces bases.
- **GLEIF** (Global Legal Entity Identifier Foundation) : les identifiants LEI des émetteurs, publiés sous licence CC0 ([conditions d'utilisation](https://www.gleif.org/en/meta/lei-data-terms-of-use)).

Ce projet est indépendant : il n'est ni soutenu ni validé par l'ESMA ou GLEIF.

## Licence

[MIT](LICENSE)
