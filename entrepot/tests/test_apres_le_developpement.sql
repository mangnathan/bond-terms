-- Découpage dans le temps (ADR 0001) : tout document de test est approuvé après le dernier
-- document de développement. Une ligne renvoyée signale une fuite du test vers le développement.
select developpement.derniere, test.premiere
from
    (select max(date_approbation) as derniere from {{ ref('documents') }} where jeu = 'developpement') as developpement,
    (select min(date_approbation) as premiere from {{ ref('documents') }} where jeu = 'test') as test
where developpement.derniere >= test.premiere
