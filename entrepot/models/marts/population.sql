-- Une ligne par obligation de la population, avec son émetteur et ses documents d'émission.
with documents_par_isin as (
    select isin, count(distinct document_id) as nb_documents
    from {{ ref('stg_registre_documents') }}
    where type_document in ('FTWS', 'STDA')
    group by isin
)

select
    population.isin,
    population.issuer_lei as lei_emetteur,
    emetteurs.nom as emetteur,
    emetteurs.secteur,
    firds.devise,
    firds.date_echeance,
    firds.type_taux,
    coalesce(documents_par_isin.nb_documents, 0) as nb_documents
from {{ source('brut', 'population') }} as population
inner join {{ ref('emetteurs') }} as emetteurs on emetteurs.lei = population.issuer_lei
left join {{ ref('stg_firds_titres') }} as firds on firds.isin = population.isin
left join documents_par_isin on documents_par_isin.isin = population.isin
