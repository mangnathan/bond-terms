-- La vérité terrain ne doit contenir qu'une ligne par couple document-ISIN.
select document_id, isin, count(*) as lignes
from {{ ref('verite_terrain') }}
group by document_id, isin
having count(*) > 1
