-- Valeurs de FIRDS typées : c'est la vérité terrain du niveau A (ADR 0001).
select
    isin,
    {{ absent_si_vide('cfi') }} as cfi,
    {{ absent_si_vide('issuer_lei') }} as lei_emetteur,
    {{ absent_si_vide('currency') }} as devise,
    {{ nombre('nominal_amount') }} as montant_nominal_total,
    {{ nombre('denomination') }} as valeur_nominale,
    {{ jour('maturity_date') }} as date_echeance,
    {{ absent_si_vide('rate_type') }} as type_taux,
    {{ nombre('fixed_rate') }} as taux_fixe,
    {{ absent_si_vide('reference_rate') }} as reference_taux_variable,
    {{ absent_si_vide('reference_term') }} as duree_reference,
    {{ nombre('spread_bps') }} as marge_points_de_base,
    {{ absent_si_vide('seniority') }} as rang,
    {{ jour('first_trade_date') }} as date_premiere_negociation,
    {{ absent_si_vide('full_name') }} as nom_complet
from {{ source('brut', 'firds_titres') }}
