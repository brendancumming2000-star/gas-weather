# GFS temperatures, HDD normals, and stratospheric diagnostics

## Live operational source

The adapter downloads NOAA's operational deterministic GFS via its free public
AWS bucket. No account or API key is needed. It uses the `pgrb2.1p00` product,
which has a regular 1° global grid and forecast output through hour 384.

- [NOAA GFS product documentation](https://www.nco.ncep.noaa.gov/pmb/products/gfs/)
- [Public NOAA GFS data registry](https://registry.opendata.aws/noaa-gfs-bdp-pds/)
- [NOAA product inventory and units](https://www.nco.ncep.noaa.gov/pmb/products/gfs/gfs.t00z.pgrb2.1p00.anl.shtml)
- Example URL pattern: `https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.1p00.fFFF.idx`

The adapter checks candidates in reverse chronological order and requires a
published hour-384 index before choosing a run. Initialization times are read
from the index and checked again inside every decoded GRIB message. The encoded
valid time must also equal initialization plus forecast lead. The displayed
model run is therefore a verified initialization, not a download timestamp or a
guess based on a fixed publication delay. `observed_at` uses that initialization
time for source-freshness checks; `retrieved_at` records download completion.
Refreshing an old cached model run therefore cannot make its source appear fresh.

Each index supplies byte offsets for the fields of interest. HTTP Range
requests retrieve these messages rather than full global files. A request that
does not return the exact requested range is rejected before reading the body.
The `eccodes` package decodes GRIB2; actual metadata units are checked.

## Surface aggregation

Each of the eight configured regions is represented by the nearest 1° GFS grid
point to one reference station. `grid_points` records the selected coordinates
and distance. The app's region weights come separately from Census population;
the GFS adapter does not apply or alter those weights.

For each of **15 complete future UTC calendar days**, temperature is the average
of the instantaneous 00, 06, 12, and 18 UTC values. The current incomplete UTC day
is excluded. For example, a refresh at 23:30 Central on September 14 is already
September 15 UTC; the first full future UTC date is September 16. This is an
approximation to a daily mean, not a native daily-mean product or an exact
local-day mean. Four samples capture some diurnal variation, but cannot remove
sampling error or a coastal/mountain grid bias.

Kelvin is converted with `(K − 273.15) × 9/5 + 32`. Regional daily HDD is
`max(65 − daily_mean_F, 0)`. The shared HDD model then applies population weights.
An incomplete temperature horizon raises an ingestion error so the application
can retain the timestamped last successful forecast. It never fills missing
dates with invented temperatures.

## Observed daily climatology

Normals are NOAA NCEI **1991–2020 daily station normals**, fetched independently
for the eight reference stations configured in `config.py`.

- [NOAA U.S. Climate Normals](https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals)
- [Native daily CSV directory](https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/)
- [Daily normals documentation](https://www.ncei.noaa.gov/data/normals-daily/1991-2020/doc/Normals_DLY_Documentation_1991-2020.pdf)

URL pattern: `https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/STATION.csv`.
The adapter uses `DLY-TAVG-NORMAL` and `DLY-HTDD-NORMAL`. **This access CSV already
uses Fahrenheit and Fahrenheit degree days; do not divide these fields by 10.**
NOAA's native average daily HDD is used directly. `HDD(average temperature)` is
not the same as `average(HDD)`, particularly in shoulder seasons, so deriving a
normal HDD from normal temperature would introduce a systematic error.

The normals describe historical observed station climate, with NOAA's daily
smoothing and observation-day conventions. The GFS approximation uses UTC days
and a nearby grid cell. Those definitions differ and add error to the displayed
anomaly. A failed station is reported explicitly and its normal remains missing;
GFS temperatures for that region remain usable. Static normals are cached by
station in `data/cache/normals`; their age does not mean that their fixed
1991–2020 baseline has expired. Delete that directory to force a redownload.

## Polar-vortex fields

For the initial analysis and each forecast day's **12 UTC snapshot**, the adapter
calculates:

| Output | Calculation | Units |
|---|---|---|
| `u10_ms` | Zonal mean of UGRD at exactly 60°N, all longitudes, 10 hPa | m/s |
| `temp10_k` | Cosine-latitude-weighted mean temperature over 60–90°N at 10 hPa | K |
| `height10_m` | Cosine-latitude-weighted mean geopotential height over 60–90°N at 10 hPa | Geopotential metres |

Positive zonal wind means westerlies; negative wind means easterlies. A single
forecast easterly sample is not a confirmed sudden stratospheric warming.
The diagnostic flag only highlights an initial-westerly to forecast-easterly
transition within the November–March monitoring season. The fields are not
ensemble probabilities and no calibrated cold-outbreak score is supplied.

The [NOAA Sudden Stratospheric Warming Compendium](https://csl.noaa.gov/groups/csl8/sswcompendium/)
uses winter wind reversal for major warming identification; its
[event documentation](https://csl.noaa.gov/groups/csl8/sswcompendium/majorevents.html)
also applies daily-mean and event-separation/final-warming criteria. V1 has only
one forecast snapshot per day and does not implement those full criteria.
It therefore reports a **wind transition to investigate**, not an SSW detection.
Summer easterlies are not classified as an SSW risk. The UI uses a Moderate watch for sampled winter easterlies, explicitly distinguishing a new westerly-to-easterly transition from easterlies already present at initialization. It only assigns Low when all expected stratospheric samples are available. Incomplete coverage cannot exclude a reversal, and High is not assigned.

Historical stratospheric percentiles, vortex displacement or stretching, and
stratosphere–troposphere coupling diagnostics are not implemented. A temperature
or wind change alone cannot establish that U.S. cold will occur. The raw fields
remain available for interpretation. Stratospheric download failures are
isolated from the surface forecast and appear in `polar_vortex.warnings`.

## Cache and revision integrity

Successful decoded forecast leads are stored in `data/cache/gfs` by model
initialization, forecast hour, region-coordinate signature, and parser version.
Writes are atomic. Repeated pulls of the same lead reuse its verified values.
The application separately records every pull in SQLite. Current operational
retrievals and genuine NOAA archive retrievals share the same byte-range decoder,
unit checks, and encoded-time validation. A revision compares common valid dates.

`fetch_archived_gfs(model_run, regions=None, comparison_dates=None)` retrieves a
specific real NOAA cycle. It preserves its historical `model_run` and
`observed_at`, labels `retrieval_mode="archive"`, and records today's actual
`retrieved_at`; it never claims that the application retrieved the forecast in
the past. Requested comparison dates are clipped to full 00/06/12/18 UTC days
within that old run's 0–384-hour horizon. Missing end dates are exposed as
`excluded_dates`, and `forecast_days` reports the supported day count.

For example, comparing the September 14 18 UTC run against September 13 18 UTC
using September 16–30 dates produces 14 complete overlapping days through
September 29. September 30 lies beyond the old model's horizon and is excluded;
its temperature and revision are not extrapolated. With no comparison dates,
the archive API defaults to 15 full UTC days after its initialization day.
A missing archive raises an ingestion error instead of substituting another run.

A cold start fetches about 60 small surface messages plus 16 stratospheric
message spans and eight fixed normals CSVs. Retries are bounded and downloads
run concurrently. Refreshing a previously seen run usually reads local files
apart from checking whether a newer complete run has been published.

## Validation

On September 15, 2026 UTC, an actual cold-start fetch completed in approximately
7 seconds and returned the September 14 18 UTC initialization, 120 regional
forecast rows for September 16–30, all eight station normals, and 16
stratospheric snapshots without source warnings. Those are verification results,
not fallback data embedded in the adapter.

`tests/test_gfs.py` covers Kelvin/Fahrenheit conversion, the UTC date boundary,
complete 384-hour coverage, stale-run rejection, GRIB initialization and valid
time validation, index byte ranges, zonal/polar aggregation, and native NOAA
normal units. All tests are offline; integration is checked using a real fetch.

A subsequent live archive check retrieved the genuine September 13 18 UTC cycle
in approximately 4.6 seconds, returning 112 regional rows for September 16–29,
15 stratospheric snapshots, and no warnings. Source time remained September 13;
retrieval time was September 15. Fifteen offline GFS tests now include archive
horizon clipping for prior 6-hour, 24-hour, and 48-hour cycles and source/retrieval
provenance checks.


## Heating and cooling extension

The dashboard now computes both HDD = max(65°F − daily mean temperature, 0)
and CDD = max(daily mean temperature − 65°F, 0) for each region before applying
population weights. The station normal parser reads both `DLY-HTDD-NORMAL` and
`DLY-CLDD-NORMAL` directly in their native Fahrenheit degree-day units. CDD of
climatological mean temperature is not a substitute for mean climatological CDD.

Old heating-only station-normal caches are refreshed from NOAA. Saved forecast
snapshots are never rewritten: `attach_degree_day_normals` can enrich a copy of
legacy rows in memory from the fixed 1991–2020 station normals. CDD revisions
are derived from the temperatures already stored for matching forecast dates.
The separate cooling coefficient represents an illustrative temperature-based
estimate of gas used for electricity generation; it is not a full dispatch model.
