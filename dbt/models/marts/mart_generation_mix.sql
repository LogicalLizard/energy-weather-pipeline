-- long format (one row per hour and technology), handy for stacked area charts

select
    ts_utc,
    series as technology,
    value as generation_mwh,
    series in ('wind_onshore', 'wind_offshore', 'solar', 'biomass', 'hydro', 'other_renewables')
        as is_renewable
from {{ ref('stg_smard') }}
where series not in ('price_day_ahead', 'load')
