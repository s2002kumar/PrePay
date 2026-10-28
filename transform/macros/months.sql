{#- Calendar months are integers: year * 12 + (month - 1), identical to prepay.periods. -#}

{% macro yyyymm_to_month(column) -%}
    case
        when regexp_full_match({{ column }}, '(19|20)[0-9]{2}(0[1-9]|1[0-2])')
            then cast(substr({{ column }}, 1, 4) as integer) * 12
                + cast(substr({{ column }}, 5, 2) as integer) - 1
    end
{%- endmacro %}

{% macro iso_to_month(text) -%}
    (cast(substr('{{ text }}', 1, 4) as integer) * 12 + cast(substr('{{ text }}', 6, 2) as integer) - 1)
{%- endmacro %}

{% macro date_to_month(expression) -%}
    (year({{ expression }}) * 12 + month({{ expression }}) - 1)
{%- endmacro %}

{% macro month_end_date(month) -%}
    (make_date(cast(({{ month }}) // 12 as integer), cast(({{ month }}) % 12 + 1 as integer), 1)
        + interval 1 month - interval 1 day)::date
{%- endmacro %}

{% macro cutoff_month() -%}
    {{ iso_to_month(var('performance_cutoff')) }}
{%- endmacro %}

{% macro sentinel_int(column, sentinels) -%}
    case
        when {{ column }} = ''
            {%- for value in sentinels %} or {{ column }} = '{{ value }}'{% endfor %}
            then null
        else try_cast({{ column }} as integer)
    end
{%- endmacro %}

{% macro sentinel_text(column, sentinels=[]) -%}
    case
        when {{ column }} = ''
            {%- for value in sentinels %} or {{ column }} = '{{ value }}'{% endfor %}
            then null
        else {{ column }}
    end
{%- endmacro %}
