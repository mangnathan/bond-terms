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
    firds.rang is not null as rang_comparable,
    -- Le couple n'entre dans la vérité terrain que si le document cite l'ISIN (ADR 0002).
    -- Pas de valeur par défaut : un couple sans contrôle fait échouer le test not_null.
    rattachement.isin_cite,
    -- Produit structuré que FIRDS déclare comme une obligation classique (ADR 0003).
    rattachement.produit_structure
from {{ ref('stg_decoupage') }} as decoupage
inner join {{ ref('stg_firds_titres') }} as firds on firds.isin = decoupage.isin
left join {{ ref('emetteurs') }} as emetteurs on emetteurs.lei = firds.lei_emetteur
left join documents_par_isin on documents_par_isin.isin = decoupage.isin
left join {{ ref('stg_rattachement') }} as rattachement
    on rattachement.document_id = decoupage.document_id and rattachement.isin = decoupage.isin
