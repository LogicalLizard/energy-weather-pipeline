-- hourly table for the dashboard: price, load and generation next to national weather.
-- left join so day-ahead prices for tomorrow stay visible before weather data exists.

with energy as (

    select
        ts_utc,
        max(case when series = 'price_day_ahead' then value end) as price_eur_mwh,
        max(case when series = 'load' then value end) as load_mwh,
        max(case when series = 'wind_onshore' then value end)
            + max(case when series = 'wind_offshore' then value end) as wind_mwh,
        max(case when series = 'solar' then value end) as solar_mwh
    from {{ ref('stg_smard') }}
    group by ts_utc

),

weather as (

    -- average over the six locations as a simple "national" weather signal
    select
        ts_utc,
        avg(wind_speed_ms) as wind_speed_ms,
        avg(radiation_wm2) as radiation_wm2,
        avg(temperature_c) as temperature_c
    from {{ ref('stg_open_meteo') }}
    group by ts_utc

)

select
    energy.ts_utc,
    energy.price_eur_mwh,
    energy.load_mwh,
    energy.wind_mwh,
    energy.solar_mwh,
    weather.wind_speed_ms,
    weather.radiation_wm2,
    weather.temperature_c
from energy
left join weather using (ts_utc)
-- smard weeks start Monday 00:00 Berlin time, weather weeks Monday 00:00 UTC;
-- clip the two leading energy-only hours so the mart starts where both sources exist
where energy.ts_utc >= (select min(ts_utc) from weather)
