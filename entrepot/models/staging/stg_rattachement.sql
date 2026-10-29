select
    document_id,
    isin,
    isin_cite = 'True' as isin_cite,
    produit_structure = 'True' as produit_structure
from {{ source('brut', 'rattachement') }}
