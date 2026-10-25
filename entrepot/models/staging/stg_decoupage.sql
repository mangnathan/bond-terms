select
    document_id,
    isin,
    {{ absent_si_vide('issuer_lei') }} as lei_emetteur,
    document_type as type_document,
    {{ jour('approval_date') }} as date_approbation,
    {{ absent_si_vide('languages') }} as langues,
    jeu
from {{ source('brut', 'decoupage') }}
