# Gas Weather

A natural gas weather dashboard for people who are new to weather. Start with one question: **Will people need more heating or air conditioning, and has that expectation changed?**

**[Read the beginner’s quick-start guide](docs/quick-start.md)** for a two-minute routine, simple examples, and the meaning of every main number.

- Cold weather can increase gas use for heating. Hot weather can increase electricity use for air conditioning, which can increase gas use at power plants.
- The overview opens with **The simple read**, a plain-English demand summary, followed immediately by four NOAA temperature maps and a short polar-vortex guide.
- The maps show the previous day's 6–10 and 8–14 day outlooks, the latest weekly Weeks 3–4 outlook available by that day, and the latest November–January seasonal outlook. Actual issue and valid dates stay visible.
- Demand estimates compare with **usual weather**. Forecast changes are shown separately, using the same future dates in each forecast.
- Heating and cooling contributions stay visible, including when they offset each other. An interactive temperature example explains both before asking you to interpret charts.
- Longer-range NOAA maps show the odds of broad weather patterns. Advanced circulation clues, calculations, and source details remain available in their own sections.

**All operational inputs come from free public sources. No accounts, API keys, or paid feeds are required.** Forecasts and observations are downloaded from their real sources; unavailable data remain unavailable. Local snapshots preserve forecast history.

The gas estimates use editable, uncalibrated assumptions. They explain possible weather-related demand differences; they do not predict gas prices or recommend trades. [EIA explains the heating, cooling, and gas connection](https://www.eia.gov/energyexplained/natural-gas/factors-affecting-natural-gas-prices.php).

## Screenshots

The beginner-friendly interface, captured September 15, 2026 (UTC). The overview leads with the simple read, four NOAA maps, and a polar-vortex guide. Open the dashboard for current readings.

- [Simple read and daily NOAA maps](docs/overview-noaa.png)
- [Weeks 3–4 and November–January maps](docs/seasonal-noaa.png)
- [Polar-vortex guide](docs/vortex-guide.png)
- [Heating and cooling tutorial](docs/heating-cooling-explained.png)
- [Subseasonal outlook with map-reading guide](docs/outlook-explained.png)


## Run locally

For a link that works on someone else's computer, see [online hosting](docs/hosting.md).

From the project directory:

```bash
./run.sh
```

Open [the local dashboard](http://localhost:8501). Stop the process with `Ctrl+C` in its terminal.

This address runs on your Mac. Keep the server running while using the dashboard; closing its terminal or restarting the Mac can stop it. If the browser says the site cannot be reached, run `./run.sh` again and reload the page.

Python **3.12** is the tested runtime. On the first launch, `run.sh` creates `.venv` and installs `requirements.txt`. If `uv` is installed, it uses `uv` to provision Python 3.12 and install dependencies. Otherwise it requires Python 3.11+ and uses the available `python3` and `pip`; Python 3.12 is recommended. The first launch needs internet access to install packages and download data. Subsequent launches reuse the environment and local caches.

The launcher also forwards Streamlit options:

```bash
./run.sh --server.port 8502
```

### Manual setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

To install into an existing environment with `uv`:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

The main dependencies are Streamlit, pandas, NumPy, Plotly, requests, ecCodes for GRIB2 decoding, and xlrd for EIA workbooks. Pytest provides the checks. Dependencies and supported version ranges live in `requirements.txt`. The implementation reads selected GRIB messages directly with ecCodes; it does not require a separate xarray/cfgrib pipeline. Platforms without a compatible ecCodes wheel may need an ecCodes system installation.

### Optional configuration

The default SQLite database is `data/weather.sqlite3`. To change its location, export a shell environment variable before starting:

```bash
export WEATHER_DB_PATH="/absolute/path/weather.sqlite3"
./run.sh
```

`.env.example` documents this optional setting. **The app does not automatically load `.env` files.** API keys are unnecessary. Other model settings, source refresh intervals, and stale thresholds are in `config.py`.

## What is in the dashboard

| Sidebar page | What it helps you understand |
| --- | --- |
| Overview | The simple read, four NOAA temperature maps, a short polar-vortex guide, then heating/cooling contributions and forecast changes |
| Heating & cooling | Daily heating and cooling needs, historical comparisons, the temperature tutorial, and the assumed gas translation |
| What changed | Changes since a prior, 24-hour-old, or 48-hour-old forecast across shared dates, regional contributions, and saved history |
| Longer-range outlook | Official CPC 6–10 day, 8–14 day, and Weeks 3–4 maps, with explanations of their colors, probabilities, and valid dates |
| Cold-weather clues | Polar vortex, NAO, Eurasian snow, and Arctic sea ice, with explanations of what each can and cannot tell you |
| Gas market | Henry Hub daily spot prices, working gas storage, weekly builds/draws, and a five-year seasonal comparison |
| Data & assumptions | A glossary, source freshness, failures, model limitations, and the optional demand score with its full calculation |

In the advanced sidebar controls, heating and cooling assumptions can be changed independently. Changing them recalculates locally. Source issue/observation dates remain distinct from download times. Daily forecast dates and operational timestamps use UTC; publications supplying only a date retain date precision. The overview's “previous day” follows the **America/New_York calendar**, matching NOAA's Eastern Time publication context.

### Maps at the top of Overview

The two-by-two map grid contains:

- **6–10 day and 8–14 day:** the outlooks issued on the previous Eastern Time calendar day.
- **Weeks 3–4:** the latest weekly outlook that was available by the end of that previous day. It is not a daily publication; its real issue date is shown.
- **November–January:** the most recent available seasonal outlook for this three-month period. As of September 15, 2026, the target is **November 2026–January 2027**. It describes one three-month average, not three separate monthly forecasts.

These saved maps are an independent `noaa_maps` source. Each image retains its source, issue date, and valid period; a missing product is labeled unavailable. The existing **Longer-range outlook** page still provides the current CPC outlooks and fuller map-reading explanations. See [NOAA homepage map provenance](docs/noaa_maps.md).

Below the maps, a short guide explains the polar vortex, clues that can precede a disruption, and the current winter-watch status. A winter vortex normally exists: the relevant question is whether changes in its circulation could help cold air move south. Those clues do not establish a U.S. cold-outbreak probability.

## Heating and cooling calculations

**HDD** means heating degree days; **CDD** means cooling degree days. Both measure distance from a standard 65°F reference. At a daily average of 55°F there are 10 HDD and 0 CDD; at 75°F there are 0 HDD and 10 CDD. The reference is a calculation convention, not a thermostat recommendation. [EIA’s degree-day explanation](https://www.eia.gov/energyexplained/units-and-calculators/degree-days.php).

### Deterministic GFS forecast

The adapter reads NOAA's public operational **GFS 1° deterministic grid**, using index files and byte-range requests to download only the needed temperature and stratospheric messages. It selects a published run with hour-384 coverage and checks initialization, valid time, and units inside the decoded GRIB messages.

The surface window contains **15 complete future UTC calendar days**. Each day's mean temperature is approximated by the average of its 00, 06, 12, and 18 UTC instantaneous forecasts. Today's incomplete UTC day is excluded. This is an approximation to a daily mean, and it is not a local-calendar-day temperature forecast.

Kelvin converts to Fahrenheit as:

```text
temperature_F = (temperature_K − 273.15) × 9/5 + 32
regional_daily_HDD = max(65 − regional_daily_mean_F, 0)
regional_daily_CDD = max(regional_daily_mean_F − 65, 0)
national_daily_HDD = Σ regional_population_weight × regional_daily_HDD
national_daily_CDD = Σ regional_population_weight × regional_daily_CDD
```

Both degree-day measures are calculated **before** population weighting. Calculating them from an already averaged national temperature would hide heating in colder regions and cooling in warmer regions. Totals add the daily values across the displayed period.

### Transparent regional population approximation

“National” means **the contiguous 48 states plus the District of Columbia**, excluding Alaska and Hawaii. Eight disjoint state groups represent 329,260,619 residents in the 2020 Census. One metro/airport reference station and its nearest GFS grid point represent each group. The actual Census apportionment CSV is checked into `data/census_apportionment.csv`; weights are calculated from its 2020 resident-population rows at startup, rather than hard-coded estimates.

| Region | Reference metro | 2020 population | National weight |
| --- | --- | ---: | ---: |
| Northeast | Boston | 35,317,454 | 10.73% |
| Midwest | Minneapolis | 21,616,921 | 6.57% |
| Great Lakes | Chicago | 47,368,533 | 14.39% |
| Mid-Atlantic | Philadelphia | 40,573,520 | 12.32% |
| South Central | Dallas | 40,774,139 | 12.38% |
| Southeast | Atlanta | 67,210,142 | 20.41% |
| Mountain | Denver | 24,919,150 | 7.57% |
| West | Los Angeles | 51,480,760 | 15.64% |

Displayed percentages are rounded; full-precision weights sum to one. State membership, station IDs, coordinates, and weights are visible in `config.py` and the sidebar. This is a deliberately coarse regional proxy: a single point cannot capture a large region's temperature distribution, terrain, heating-fuel mix, or population geography. Ingestion and weighting are separated so a population grid or larger station network can replace it later.

### NOAA daily normals

“Normal” or “usual” means NOAA NCEI's **1991–2020 daily station climatology** for the matching dates. The app uses the published `DLY-HTDD-NORMAL` and `DLY-CLDD-NORMAL` directly, alongside `DLY-TAVG-NORMAL`. These access CSV fields already use Fahrenheit and Fahrenheit degree days; they are not divided by ten.

**Average degree days are not degree days calculated from average temperature.** Published HDD and CDD normals reflect the historical distribution of temperatures. Recalculating them from the climatological mean temperature would bias comparisons near 65°F, so the app does not make that substitution.

The forecast's UTC sampling, grid-cell temperature, and NOAA's observed station-day normal differ; no bias correction is applied. Missing regional normals leave the affected national normal unavailable without redistributing weights. If either heating or cooling normals are missing, the **combined comparison with normal is unavailable**; comparisons between forecasts for the same dates can still work because they need temperatures, not normals. See [GFS and normal methodology](docs/gfs.md).

Older saved forecasts can obtain missing cooling normals in memory from NOAA's fixed climatology. This does not overwrite, delete, or change the original snapshots.

## Estimated gas demand

**Bcf** means billion cubic feet; **Bcf/d** means billion cubic feet per day. Heating and cooling use separate assumptions in `config.py` and the advanced sidebar:

| Assumption | Default |
| --- | ---: |
| `BCF_PER_NATIONAL_HDD` | 0.8 Bcf per national population-weighted HDD |
| `BCF_PER_NATIONAL_CDD` | 0.4 Bcf per national population-weighted CDD |

**Both coefficients are illustrative and have not been fitted or validated against observed gas consumption.** A persistent new default belongs in the config file.

For daily degree-day differences relative to normal or an earlier forecast:

```text
heating_difference_Bcf = daily_HDD_difference × heating_coefficient
cooling_difference_Bcf = daily_CDD_difference × cooling_coefficient
combined_daily_difference_Bcf = heating_difference_Bcf + cooling_difference_Bcf
cumulative_impact_Bcf = sum(combined_daily_difference_Bcf)
average_impact_Bcf_per_day = cumulative_impact_Bcf / comparable_day_count
```

For illustration, +2 HDD and −1 CDD on one day produce `2 × 0.8 − 1 × 0.4 = +1.2 Bcf` relative to the selected baseline. Ten such days total +12 Bcf and average +1.2 Bcf/d. This explains the units; it is not a live forecast. Separate heating and cooling contributions remain visible.

This estimates a **weather-related demand difference**, not observed or total U.S. consumption, a storage change, or a price target. Cooling is a simple proxy for gas burned to generate electricity. It does not model power dispatch, renewable output, humidity, plant efficiency, or fuel switching. Industrial activity, LNG flows, production, and freeze-offs are also outside the demand calculation.

“Versus usual weather” describes the expected difference from a historical baseline. “Versus the earlier forecast” describes a change in expectations. A forecast can remain colder than normal while becoming warmer than yesterday's forecast. Both statements can be true.

## Forecast snapshots and revision integrity

Every successful source pull appends a timestamped SQLite snapshot. Existing snapshots are not overwritten. A separate attempt log records failures. Inserts use a transaction, and nonfinite JSON values are rejected before saving.

GFS comparison rules are explicit:

- **Prior run:** the newest locally saved initialization strictly earlier than the current one. Another pull of the same initialization is not a distinct model run.
- **24 / 48 hours ago:** use the latest saved initialization at or before the target, allowing at most six additional hours of age. A 24-hour comparison can therefore use a 30-hour-old cycle. Actual initialization timestamps are displayed.
- Join on **identical valid date and region** for heating and cooling. Exclude unmatched dates; never treat missing values as zero.
- Report the number of shared days with each result. Older 15-day forecasts normally overlap fewer than 15 days of today's window. First-seven-day revisions use shared dates within the current forecast's first seven days.
- On its first successful GFS load, the app imports the original NOAA runs from 6, 24, and 48 hours earlier when the archive is accessible. These are genuine archived forecasts retrieved today, not simulated historical snapshots or records of earlier local observations. Older horizons are clipped to fully supported, matching valid dates. Failed archive downloads remain unavailable; later refreshes continue building history.

The daily GFS decoder cache and the snapshot database serve different purposes. The former avoids downloading identical verified forecast fields again; the latter records what the application actually retrieved over time. Historical source revisions are not a reconstruction of the information available to traders at every past timestamp.

## Advanced demand score and cold-weather context

The main overview explains demand versus usual weather and shows forecast revisions separately. An optional score in **Data & assumptions** combines the two demand estimates as a display heuristic. It has no fitted relationship to price, backtested edge, or calibrated probabilities:

`score = Σ weight × clip(average_daily_demand_difference / scale, −1, +1)`

| Factor | Input | Default weight | Saturation scale |
| --- | --- | ---: | ---: |
| Versus usual weather | Combined heating + cooling demand difference from normal, averaged per day | 0.65 | 2 Bcf/d |
| Versus the 24h-old forecast | Combined heating + cooling revision, averaged across shared dates | 0.35 | 1 Bcf/d |

Missing factors abstain with zero contribution; available weights are **not renormalized**. Available weight is displayed; zero coverage means unavailable, not a neutral forecast. The score requires a fresh, complete 15-day surface forecast. It uses the current editable coefficients, so it can change without a change in weather. The original heating-only score is no longer presented in the UI.

`DISPLAY_CHANGE_BCF_PER_DAY = 0.1` controls plain-English small-change labels. It is a display threshold, not statistical significance or forecast confidence. The overview's language describes estimated gas demand, not a buy/sell instruction.

Polar vortex, NAO, snow, sea ice, and longer-range map colors have **no direct Bcf or score conversion**. They remain contextual clues:

- Eastern cold risk uses the largest three-consecutive-day mean HDD anomaly within the eastern group, normalized by that group's population weight. Moderate begins at +5 HDD/day and High at +10 HDD/day. Missing or nonconsecutive coverage does not become Low risk.
- The polar-vortex watch examines sampled 60°N / 10 hPa wind in November–March. Winter easterly flow can warrant a Moderate watch; newly forecast transitions and already-existing easterlies require different interpretation. The app does not diagnose a confirmed sudden stratospheric warming, forecast a U.S. outbreak probability, or use a High vortex category. Summer seasonal easterlies are unclassified.
- NAO is dimensionless blocking context. Negative values can be relevant to eastern North America and Europe, depending on circulation placement. **European cold risk is not independently modeled.**

Raw stratospheric wind, polar temperature, and geopotential height remain visible. No historical stratospheric climatology/percentiles, vortex displacement/stretching diagnosis, or stratosphere–troposphere coupling model is implemented.

## Public data sources

| Input | Authoritative source and direct data | Scope and interpretation |
| --- | --- | --- |
| GFS temperatures and stratosphere | [NOAA GFS products](https://www.nco.ncep.noaa.gov/pmb/products/gfs/) · [public AWS data registry](https://registry.opendata.aws/noaa-gfs-bdp-pds/) | Deterministic 1° forecast, selected GRIB2 messages, through hour 384 |
| Daily station normals | [NCEI U.S. Climate Normals](https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals) · [1991–2020 daily CSV directory](https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/) | Fixed observed daily temperature, HDD, and CDD normals |
| Population weights | [U.S. Census apportionment CSV](https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/apportionment.csv) | Checked-in 2020 resident population; Lower 48 + DC |
| Observed NAO | [CPC NAO methodology](https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/nao_index.html) · [daily observed CSV](https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.cdas.z500.19500101_current.csv) | Daily standardized index; same-month 1991–2020 percentile |
| Forecast NAO | [CPC GEFS ensemble CSV](https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.gefs.z500.120days.csv) | Member mean and P10/P90 spread; prior-calendar-day initialization matched by valid date |
| 6–10 day temperatures | [CPC product](https://www.cpc.ncep.noaa.gov/products/predictions/610day/) · [map](https://www.cpc.ncep.noaa.gov/products/predictions/610day/610temp.new.gif) | Probabilistic period-average outlook; state category summaries |
| 8–14 day temperatures | [CPC product](https://www.cpc.ncep.noaa.gov/products/predictions/814day/) · [map](https://www.cpc.ncep.noaa.gov/products/predictions/814day/814temp.new.gif) | Probabilistic period-average outlook; state category summaries |
| Weeks 3–4 temperatures | [CPC outlook and discussion](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/) · [map](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/gifs/WK34temp.gif) | Operational subseasonal substitute for raw SubX ingestion |
| Eurasian snow | [Rutgers weekly Eurasian text series](https://climate.rutgers.edu/snowcover/files/wkcov.eurasia.txt) · [unit documentation](https://climate.rutgers.edu/snowcover/table_area.php?ui_set=2&ui_sort=0) | Continental extent in km², converted to million km²; same-Rutgers-week 1991–2020 baseline |
| Arctic sea ice | [NSIDC Sea Ice Index v4](https://nsidc.org/data/g02135/versions/4) · [daily Arctic CSV](https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv) | Extent already in million km²; locally computed same-month/day 1991–2020 baseline |
| Henry Hub price | [EIA daily spot series](https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm) · [XLS](https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls) | Daily physical spot USD/MMBtu; not a futures quote |
| Working gas storage | [EIA Lower 48 series](https://www.eia.gov/dnav/ng/hist/nw2_epg0_swo_r48_bcfw.htm) · [XLS](https://www.eia.gov/dnav/ng/hist_xls/NW2_EPG0_SWO_R48_BCFw.xls) | Weekly working gas in Bcf; stock change and local five-year seasonal comparison |

Detailed methods, source-specific caveats, and live integration evidence are in:

- [GFS, station normals, and stratospheric fields](docs/gfs.md).
- [CPC, NAO, Rutgers snow, and NSIDC sea ice](docs/context_sources.md).
- [Previous-day NOAA maps and the November–January seasonal outlook](docs/noaa_maps.md).
- [EIA prices, storage, and five-year comparison](docs/eia.md).

### Substitutions and context limitations

The operational CPC Weeks 3–4 outlook supplies the subseasonal view; raw NOAA SubX archives are not ingested. Map probabilities describe the **average across the labeled period**, not a number of degrees or the weather on every day. CPC regional summaries come from official categories and discussion; they are not population-weighted probabilities or synthetic degree days. Map bytes are saved with each outlook snapshot so a cached issue cannot silently display a newer map. If image download fails, the source link remains available; an image is reused only for the identical issue date.

Rutgers supplies **Eurasian continental extent**, not a custom Siberia-only area, snow depth, or snow water equivalent. Its weekly publication can lag. Seasonal comparisons preserve Rutgers week numbering, not ISO weeks; absent week changes remain missing. Autumn snow is probabilistic context and does not mechanically imply a U.S. cold event.

NSIDC is total Arctic extent, not regional ice concentration, ice area, or volume. The application uses its own 1991–2020 comparison baseline, which differs from NSIDC's commonly published 1981–2010 climatology. Recent values can be provisional.

EIA weekly stock change includes possible reclassifications; it is not always EIA's adjusted net injection/withdrawal. The local five-year storage benchmark matches the nearest calendar-season observation in each of the preceding five completed calendar years, requires all five, and exposes the selected dates. It can differ from EIA's published five-year average/range.

## Refresh, freshness, and failure behavior

The app checks source cache ages when a **new Streamlit session starts**. The first successful GFS load also attempts a one-time import of recent NOAA comparison cycles. The sidebar's refresh button forces a fresh pull. The homepage map cache also checks the requested previous Eastern Time date on app reruns: a date change makes that bundle eligible for a new pull even within its usual cache interval. There is **no background scheduler or automatic polling loop**; leaving a browser tab open does not schedule later retrievals. Changing a demand coefficient recalculates locally; it can also trigger the date check, without forcing every source to download again.

| Source group | Cache refresh eligibility | Default stale observation warning |
| --- | ---: | ---: |
| GFS | 6 hours | 18 hours |
| CPC / NAO | 6 hours | 72 hours |
| Rutgers snow | 24 hours | 10 days |
| NSIDC sea ice | 24 hours | 5 days |
| EIA | 12 hours | 10 days |
| Station normals | Fixed baseline cached on disk | No age-based expiry of the fixed normal |

Refresh eligibility generally uses **last successful retrieval time**; the homepage map bundle also checks its requested previous date. Freshness uses the **source observation/issue date**. These are different clocks. Individual maps, CPC products, and the two EIA series retain separate dates; a fresh bundled source timestamp does not establish that every subproduct is current. Thresholds are configurable display defaults, not guarantees about provider publication schedules.

Run a refresh without launching the UI:

```bash
.venv/bin/python -m data_sources.refresh --force
```

Or target selected sources:

```bash
.venv/bin/python -m data_sources.refresh --force --sources gfs eia
```

Omit `--force` to respect the cache intervals. Requests retry transient failures with bounded timeouts. A failed source retains its last successful snapshot and reports the failure; other sources continue. With no previous success, its panel shows unavailable. Past GFS dates are excluded, and stale or incomplete surface forecasts cannot generate the current overall summary. Individual CPC products and stratospheric fields can report partial-availability warnings.

SQLite snapshots and downloaded decoder/normal caches are local, and ignored by Git. Preserve `data/weather.sqlite3` to keep run-comparison history. Removing a cache directory forces real downloads; removing the database discards the accumulated comparison history.

## Project structure

```text
app.py                     Streamlit layout, controls, and source presentation
config.py                  Region definitions, weights, assumptions, and thresholds
components/                Charts and beginner-friendly page components
data_sources/
    common.py              Bounded, retried HTTP access
    gfs.py                 Operational GFS extraction and decoded-field cache
    normals.py             NOAA daily station normals
    cpc.py                 Observed/ensemble NAO and CPC outlooks
    noaa_maps.py           Previous-day outlook maps and latest NDJ seasonal map
    rutgers_snow.py         Weekly Eurasian snow
    nsidc.py                Daily Arctic sea-ice extent
    eia.py                  Spot prices and storage
    refresh.py              Source orchestration, persistence, and CLI refresh
    cache_merge.py          Independent CPC subproduct recovery
models/
    hdd.py                 Temperatures, weighted HDD/CDD, and valid-date comparisons
    gas_demand.py          Separate and combined heating/cooling demand differences
    signals.py             Explicit factor scores and conservative context heuristics
storage/database.py        SQLite snapshots and refresh-attempt audit
storage/bootstrap.py       One-time import of genuine recent NOAA archived runs
data/census_apportionment.csv
                           Source population data used to derive weights
docs/                      Detailed source and calculation notes
tests/                     Mathematical, parsing, date, and persistence checks
requirements.txt           Dependencies
run.sh                     One-command local startup
```

## Validation and troubleshooting

Run the test suite:

```bash
.venv/bin/python -m pytest -q
```

Tests cover temperature and degree-day calculations, native NOAA normal units, regional weighting, missing/nonfinite inputs, gas-demand dimensions and signs, matched dates, source parsing, stratospheric calculations, snow/ice climatology, storage benchmarks, append-only history, and comparison integrity. Streamlit integration checks use isolated data. Offline fixtures are confined to tests; runtime panels use downloaded observations. The test command reports the current count.

For a repeatable live integration check:

```bash
.venv/bin/python scripts/verify_live.py
```

This performs two actual refreshes, verifies all sources and CPC map images, checks all eight normals and 15 forecast dates, and asserts that every earlier source snapshot remains unchanged. It writes the timestamped result to [docs/live_validation.json](docs/live_validation.json). These checks append real data to your local history.

Real integration checks also use the refresh command above. Review both its per-source results and the dashboard's source audit: tests passing alone cannot prove that a public endpoint is currently available. Source-specific documents record actual development-time live fetches, including returned dates and coverage.

The [cooling validation report](docs/cooling_validation.json) records the live GFS cooling calculation, complete NOAA cooling normals for all eight regions, separate heating/cooling contributions, and unchanged saved forecast history.

Common situations:

- **No 24-hour revision:** the matching archived run may be inaccessible or outside the archive window. Use “Import missing recent NOAA cycles” in the saved-history expander, or run `.venv/bin/python -m storage.bootstrap`. Repeated pulls of one cycle do not create distinct comparisons.
- **Source warning after a refresh:** inspect the source's observation date and last attempt. It may have failed, or the provider may simply not have published newer observations.
- **No comparison with usual weather:** heating or cooling normals may be unavailable for a region. Forecast temperatures and changes between saved forecasts can remain usable; missing normal data are not invented or treated as zero.
- **A dependency is missing in an existing `.venv`:** reinstall `requirements.txt` with that environment's Python or with `uv pip`. The launcher only bootstraps when `.venv/bin/python` does not exist.
- **No source succeeds:** verify internet access and access to the direct source links. GFS requests require servers/proxies to honor HTTP byte ranges.

## Three highest-value next improvements

1. **Add forecast ensembles and historical verification.** Ingest GEFS temperature members, preserve forecasts, and measure probabilities and reliability of regional multi-day cold tails, rather than relying on one deterministic trajectory.
2. **Replace the eight-station approximation with a demand grid.** Use finer population and heating-fuel information, represent electricity demand geography, and align forecast/climatology day definitions with bias correction.
3. **Calibrate the heating and cooling conversion.** Fit seasonal and nonlinear relationships to observed gas-demand data, model power-generation conditions and supply context, and validate uncertainty on data excluded from fitting.

These improvements would make the dashboard more useful for gas-demand research while preserving visible inputs, versioned forecasts, and interpretable calculations.
