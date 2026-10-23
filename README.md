# bond-terms

Extraction des conditions des obligations (montant, échéance, taux, clauses) à partir des documents publiés dans le registre des prospectus de l'ESMA, avec un contrôle sur la base de référence FIRDS.

L'utilisateur visé est l'équipe « référentiel titres » d'une banque ou d'une société de gestion, qui crée aujourd'hui ses fiches de titres à la main ou les achète à un fournisseur de données. Chaque valeur extraite sera accompagnée d'une citation exacte du document, vérifiée par le code ; les cas douteux iront en revue humaine, et un rapport signalera les écarts entre le document et FIRDS.

## Avancement

| Version | Contenu | État |
|---|---|---|
| v0.0 | Cadrage : population, vérité terrain, seuils fixés avant toute extraction, référence humaine | Terminé |
| v0.1 | Collecte (FIRDS, registre, PDF), date de coupure du test, entrepôt de données | À venir |
| v0.2 | Extracteur à règles contre LLM sur les champs vérifiables, test ouvert une seule fois | À venir |
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

## Structure du dépôt

```
src/bond_terms/       code du projet (lecture de FIRDS, règle « obligation classique »)
scripts/feasibility/  scripts de l'étude de faisabilité et de la saisie chronométrée
scripts/docs/         compilation des rapports LaTeX
tests/                tests unitaires
docs/adr/             décisions d'architecture (une par version)
docs/v0.0-cadrage/    rapport LaTeX et chiffres produits par les scripts
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
```

Le registre des prospectus évolue en continu : les totaux par segment peuvent varier de quelques dizaines de documents d'un jour à l'autre.

## Données

Le projet utilise uniquement des données publiques :

- **ESMA** (Autorité européenne des marchés financiers) : la base de référence des instruments financiers FIRDS et le registre des prospectus. Source : ESMA, reproduction autorisée avec mention de la source ([mentions légales](https://www.esma.europa.eu/legal-notice)). Le dépôt ne contient aucun document de l'ESMA : seulement des identifiants (ISIN, liens) et des chiffres calculés à partir de ces bases.
- **GLEIF** (Global Legal Entity Identifier Foundation) : les identifiants LEI des émetteurs, publiés sous licence CC0 ([conditions d'utilisation](https://www.gleif.org/en/meta/lei-data-terms-of-use)).

Ce projet est indépendant : il n'est ni soutenu ni validé par l'ESMA ou GLEIF.

## Licence

[MIT](LICENSE)
