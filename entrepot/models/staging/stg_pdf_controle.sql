select
    document_id,
    jeu,
    {{ dbt.safe_cast(absent_si_vide('pages'), dbt.type_int()) }} as pages,
    {{ dbt.safe_cast(absent_si_vide('pages_sans_texte'), dbt.type_int()) }} as pages_sans_texte,
    {{ dbt.safe_cast(absent_si_vide('caracteres'), dbt.type_int()) }} as caracteres,
    rubrique_echeance = 'True' as rubrique_echeance,
    {{ absent_si_vide('erreur') }} as erreur_lecture
from {{ source('brut', 'pdf_controle') }}
