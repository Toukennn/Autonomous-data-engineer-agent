{% test quality_unique_combination(model, columns) %}

select
{% for column in columns %}
    {{ adapter.quote(column) }}{% if not loop.last %},{% endif %}
{% endfor %},
    count(*) as duplicate_count
from {{ model }}
group by
{% for column in columns %}
    {{ adapter.quote(column) }}{% if not loop.last %},{% endif %}
{% endfor %}
having count(*) > 1

{% endtest %}


{% test quality_accepted_values(
    model,
    column_name,
    values_json
) %}

select *
from {{ model }}
where
    {{ adapter.quote(column_name) }} is not null
    and to_jsonb(
        {{ adapter.quote(column_name) }}
    ) not in (
{% for value in values_json %}
        '{{ value | replace("'", "''") }}'::jsonb{% if not loop.last %},{% endif %}
{% endfor %}
    )

{% endtest %}


{% test quality_range(
    model,
    column_name,
    min_value=none,
    max_value=none,
    inclusive_min=true,
    inclusive_max=true
) %}

select *
from {{ model }}
where
    {{ adapter.quote(column_name) }} is not null
    and (
        false

{% if min_value is not none %}
{% if inclusive_min %}
        or {{ adapter.quote(column_name) }} < {{ min_value }}
{% else %}
        or {{ adapter.quote(column_name) }} <= {{ min_value }}
{% endif %}
{% endif %}

{% if max_value is not none %}
{% if inclusive_max %}
        or {{ adapter.quote(column_name) }} > {{ max_value }}
{% else %}
        or {{ adapter.quote(column_name) }} >= {{ max_value }}
{% endif %}
{% endif %}

    )

{% endtest %}


{% test quality_row_count(
    model,
    min_rows=0,
    max_rows=none
) %}

with quality_count as (

    select
        count(*)::bigint as row_count
    from {{ model }}

)

select *
from quality_count
where
    row_count < {{ min_rows }}

{% if max_rows is not none %}
    or row_count > {{ max_rows }}
{% endif %}

{% endtest %}