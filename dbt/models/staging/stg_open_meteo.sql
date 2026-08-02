select
    timestamp as ts_utc,
    location,
    temperature_2m as temperature_c,
    wind_speed_100m as wind_speed_ms,
    shortwave_radiation as radiation_wm2
from {{ source('raw', 'open_meteo') }}
