"""All judgmental parameters are exposed here; none are calibrated trading edges."""
from pathlib import Path
import csv
import os

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('WEATHER_DB_PATH', str(ROOT / 'data' / 'weather.sqlite3')))
BCF_PER_NATIONAL_HDD = 0.8  # Illustrative Bcf per national weighted HDD; NOT fitted.
FORECAST_DAYS = 15
REFRESH_HOURS = {'gfs': 6, 'cpc': 6, 'noaa_maps': 6, 'snow': 24, 'ice': 24, 'eia': 12}
STALE_HOURS = {'gfs': 18, 'cpc': 72, 'noaa_maps': 72, 'snow': 24 * 10, 'ice': 24 * 5, 'eia': 24 * 10}
SIGNAL_WEIGHTS = {'HDD anomaly': 0.55, '24h HDD revision': 0.30, 'Eastern concentration': 0.15,
                  'Polar vortex': 0.0, 'NAO': 0.0, 'Subseasonal': 0.0, 'Eurasian snow': 0.0}
# Saturation scales in weighted HDD over 15 days; judgmental display settings.
SIGNAL_SCALES = {'HDD anomaly': 30.0, '24h HDD revision': 15.0, 'Eastern concentration': 15.0}
EASTERN_REGIONS = ['Northeast', 'Great Lakes', 'Mid-Atlantic']
CENSUS_SOURCE = 'https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/apportionment.csv'
# Disjoint lower-48 + DC groups; one station represents each entire region in V1.
_REGION_SPECS = [
    ('Northeast', 'Boston', 42.36, -71.01, 'USW00014739', ['Maine','New Hampshire','Vermont','Massachusetts','Rhode Island','Connecticut','New York']),
    ('Midwest', 'Minneapolis', 44.88, -93.23, 'USW00014922', ['Minnesota','Iowa','Missouri','North Dakota','South Dakota','Nebraska','Kansas']),
    ('Great Lakes', 'Chicago', 41.98, -87.90, 'USW00094846', ['Wisconsin','Michigan','Illinois','Indiana','Ohio']),
    ('Mid-Atlantic', 'Philadelphia', 39.87, -75.23, 'USW00013739', ['Pennsylvania','New Jersey','Delaware','Maryland','District of Columbia','Virginia','West Virginia']),
    ('South Central', 'Dallas', 32.90, -97.04, 'USW00003927', ['Texas','Oklahoma','Arkansas','Louisiana']),
    ('Southeast', 'Atlanta', 33.63, -84.44, 'USW00013874', ['Kentucky','Tennessee','North Carolina','South Carolina','Georgia','Florida','Alabama','Mississippi']),
    ('Mountain', 'Denver', 39.83, -104.66, 'USW00003017', ['Montana','Idaho','Wyoming','Colorado','New Mexico','Arizona','Utah','Nevada']),
    ('West', 'Los Angeles', 33.94, -118.41, 'USW00023174', ['Washington','Oregon','California']),
]
with (ROOT / 'data' / 'census_apportionment.csv').open() as f:
    _pop = {r['Name']: int(r['Resident Population'].replace(',', '')) for r in csv.DictReader(f) if r['Year'] == '2020' and r['Geography Type'] == 'State'}
_total = sum(_pop[s] for *_, states in _REGION_SPECS for s in states)
REGIONS = [dict(name=n, city=c, latitude=lat, longitude=lon, normal_station=station,
                states=states, population=sum(_pop[s] for s in states),
                weight=sum(_pop[s] for s in states) / _total)
           for n,c,lat,lon,station,states in _REGION_SPECS]

# Cooling affects gas indirectly through electricity generation. This coefficient
# is an illustrative sensitivity, not a fitted national power-sector elasticity.
BCF_PER_NATIONAL_CDD = 0.4
DEMAND_SIGNAL_WEIGHTS = {'Versus usual weather': 0.65, 'Versus the 24h-old forecast': 0.35}
DEMAND_SIGNAL_SCALES = {'Versus usual weather': 2.0, 'Versus the 24h-old forecast': 1.0}  # Bcf/day
DISPLAY_CHANGE_BCF_PER_DAY = 0.10  # Small-change label only; not statistical significance.
