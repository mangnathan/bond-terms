select
    isin,
    {{ absent_si_vide('issuer_lei') }} as lei_emetteur,
    document_id,
    document_type as type_document,
    {{ jour('approval_date') }} as date_approbation,
    {{ dbt.safe_cast(absent_si_vide('isins_in_document'), dbt.type_int()) }} as nb_isins_cites,
    {{ absent_si_vide('home_member_state') }} as pays_approbation,
    {{ absent_si_vide('languages') }} as langues
from {{ source('brut', 'registre_documents') }}
