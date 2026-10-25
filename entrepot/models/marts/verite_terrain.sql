-- Vérité terrain du niveau A : une ligne par couple document-ISIN du découpage, avec les valeurs
-- officielles de FIRDS et les règles de comparabilité de l'ADR 0001.
with documents_par_isin as (
    select isin, count(distinct document_id) as nb_documents
    from {{ ref('stg_registre_documents') }}
    where type_document in ('FTWS', 'STDA')
    group by isin
)

select
    decoupage.document_id,
    decoupage.isin,
    decoupage.jeu,
    coalesce(emetteurs.nom, 'autre émetteur') as emetteur,
    coalesce(emetteurs.secteur, 'autre') as secteur,
    firds.lei_emetteur,
    firds.devise,
    firds.date_echeance,
    firds.type_taux,
    firds.taux_fixe,
    firds.reference_taux_variable,
    firds.duree_reference,
    firds.marge_points_de_base,
    firds.valeur_nominale,
    firds.montant_nominal_total,
    firds.rang,
    -- Le montant n'est comparé que pour un ISIN à document unique : un abondement change le total.
    coalesce(documents_par_isin.nb_documents, 0) = 1 as montant_comparable,
    -- Le rang n'est comparé que lorsque FIRDS le renseigne.
    firds.rang is not null as rang_comparable
from {{ ref('stg_decoupage') }} as decoupage
inner join {{ ref('stg_firds_titres') }} as firds on firds.isin = decoupage.isin
left join {{ ref('emetteurs') }} as emetteurs on emetteurs.lei = firds.lei_emetteur
left join documents_par_isin on documents_par_isin.isin = decoupage.isin
