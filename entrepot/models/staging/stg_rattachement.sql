select
    document_id,
    isin,
    isin_cite = 'True' as isin_cite
from {{ source('brut', 'rattachement') }}
