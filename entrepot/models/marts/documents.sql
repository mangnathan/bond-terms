-- Une ligne par document du découpage, avec son jeu et le contrôle de lecture de son PDF.
with par_document as (
    select
        document_id,
        min(jeu) as jeu,
        min(type_document) as type_document,
        min(date_approbation) as date_approbation,
        min(langues) as langues,
        count(distinct isin) as nb_isins
    from {{ ref('stg_decoupage') }}
    group by document_id
)

select
    par_document.document_id,
    par_document.jeu,
    par_document.type_document,
    par_document.date_approbation,
    par_document.langues,
    par_document.nb_isins,
    controle.pages,
    controle.pages_sans_texte,
    -- Aucune page avec du texte : document scanné, illisible sans reconnaissance d'image.
    coalesce(controle.pages > 0 and controle.pages_sans_texte = controle.pages, false) as scanne,
    controle.rubrique_echeance,
    controle.erreur_lecture
from par_document
left join {{ ref('stg_pdf_controle') }} as controle on controle.document_id = par_document.document_id
