{# Nombre à virgule en double précision. Le type « float » de DuckDB est sur 32 bits : un taux
   de 3,873 y deviendrait 3,8729999, et la comparaison à 4 décimales de l'ADR échouerait. #}
{% macro type_double() %}
    {{ return(adapter.dispatch('type_double', 'bond_terms')()) }}
{% endmacro %}

{% macro default__type_double() %}double{% endmacro %}

{% macro bigquery__type_double() %}float64{% endmacro %}

{# Texte vide ou fait d'espaces : valeur absente. #}
{% macro absent_si_vide(colonne) %}nullif(trim({{ colonne }}), ''){% endmacro %}

{% macro nombre(colonne) %}{{ dbt.safe_cast(absent_si_vide(colonne), type_double()) }}{% endmacro %}

{% macro jour(colonne) %}{{ dbt.safe_cast(absent_si_vide(colonne), 'date') }}{% endmacro %}
