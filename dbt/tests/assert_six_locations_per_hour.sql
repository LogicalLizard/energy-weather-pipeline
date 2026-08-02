-- the "national" weather average assumes all six cities report every hour;
-- fewer would silently bias the signal towards the remaining locations
select ts_utc
from {{ ref('stg_open_meteo') }}
group by ts_utc
having count(distinct location) <> 6
