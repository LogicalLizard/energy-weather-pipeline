-- one row per hour and series; null values (hours not yet published) are dropped here
select
    timestamp as ts_utc,
    series,
    value
from {{ source('raw', 'smard') }}
where value is not null
