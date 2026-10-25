-- Les documents du test « émetteurs jamais vus » ne doivent appartenir à aucun émetteur étudié.
select verite.document_id, verite.isin
from {{ ref('verite_terrain') }} as verite
inner join {{ ref('population') }} as population on population.isin = verite.isin
where verite.jeu = 'test_nouveaux_emetteurs'
