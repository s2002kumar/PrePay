{% macro census_region(state) -%}
    case
        when {{ state }} in ('CT', 'ME', 'MA', 'NH', 'RI', 'VT', 'NJ', 'NY', 'PA') then 'northeast'
        when {{ state }} in ('IL', 'IN', 'MI', 'OH', 'WI', 'IA', 'KS', 'MN', 'MO', 'NE', 'ND', 'SD')
            then 'midwest'
        when {{ state }} in ('DE', 'DC', 'FL', 'GA', 'MD', 'NC', 'SC', 'VA', 'WV', 'AL', 'KY', 'MS',
                             'TN', 'AR', 'LA', 'OK', 'TX') then 'south'
        when {{ state }} in ('AZ', 'CO', 'ID', 'MT', 'NV', 'NM', 'UT', 'WY', 'AK', 'CA', 'HI', 'OR',
                             'WA') then 'west'
        when {{ state }} is null then null
        else 'territory'
    end
{%- endmacro %}

{% macro term_bucket(term) -%}
    case
        when {{ term }} <= 180 then '15y'
        when {{ term }} <= 240 then '20y'
        else '30y'
    end
{%- endmacro %}

{% macro matched_rate(term, rates_alias) -%}
    case when {{ term }} <= 180 then {{ rates_alias }}.rate_15y else {{ rates_alias }}.rate_30y end
{%- endmacro %}
