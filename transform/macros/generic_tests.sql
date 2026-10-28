{#- Small generic test so the project needs no third-party dbt packages (offline CI). -#}
{% test unique_combination_of_columns(model, columns) %}
select {{ columns | join(', ') }}, count(*) as rows_per_key
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
