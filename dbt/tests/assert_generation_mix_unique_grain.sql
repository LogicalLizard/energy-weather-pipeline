-- duplicate (hour, technology) rows would mean overlapping raw week files;
-- the pivot in mart_energy_weather would silently absorb them, so fail loudly here
select ts_utc, technology
from {{ ref('mart_generation_mix') }}
group by ts_utc, technology
having count(*) > 1
