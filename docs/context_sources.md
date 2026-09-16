# Context data: sources, interpretation, and validation

These connectors return genuine observations and forecasts. Retrieval time and source observation/issue date are different: refreshing a delayed source does not make its measurements current. Each product exposes its own date. HTTP failures use the application's last successful source cache; individual CPC subproducts report warnings independently.

CPC cache retention treats the NAO observed series, NAO ensemble forecast, and each of the three outlooks separately. If one component fails, its last complete cached bundle retains its actual observation/initialization/issue date while successful components update. Warnings identify retained data and recompute staleness from those dates. A fresh forecast is still downloaded when the observation endpoint fails. Cached discussions are never transplanted into a newly dated outlook.

## NOAA CPC NAO

- [Official NAO methodology and charts](https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/nao_index.html).
- [Daily CDAS observed index CSV, 1950–present](https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.cdas.z500.19500101_current.csv).
- [GEFS ensemble CSV, rolling 120 initializations](https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.gefs.z500.120days.csv).

The newer CSV observed series is used because the older `.ascii` endpoint lags. NAO values are dimensionless standardized indices. The chart uses the latest initialization, the arithmetic mean of available members on each valid date, and the 10th/90th member quantiles. These quantiles describe ensemble spread, not calibrated confidence intervals. No additional temporal smoothing is applied by this application. The prior forecast comparison selects exactly the preceding calendar-day initialization and matches identical **valid dates**; its absent final tail remains missing.

The displayed observed percentile uses the same calendar month from 1991–2020. Percentile = 100 × (count below + half of ties) / number of baseline observations. Thus a percentile describes a specified historical distribution and is not a probability of U.S. cold. Negative NAO/blocking can be relevant to eastern North America and Europe, but placement and the broader circulation matter. V1 does not translate NAO directly into Bcf or a calibrated Europe risk.

## NOAA CPC temperature outlooks

| Product | Official product | Image |
|---|---|---|
| 6–10 day | [Outlook](https://www.cpc.ncep.noaa.gov/products/predictions/610day/) | [Temperature probabilities](https://www.cpc.ncep.noaa.gov/products/predictions/610day/610temp.new.gif) |
| 8–14 day | [Outlook](https://www.cpc.ncep.noaa.gov/products/predictions/814day/) | [Temperature probabilities](https://www.cpc.ncep.noaa.gov/products/predictions/814day/814temp.new.gif) |
| Weeks 3–4 | [Outlook and discussion](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/) | [Temperature probabilities](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/gifs/WK34temp.gif) |

[Combined 6–10/8–14 discussion and state category tables](https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html) provide regional summaries without reading map colors. Northeast, Midwest, and Great Lakes summaries count state categories and are **not population weighted** or regional numeric probabilities. Weeks 3–4 summaries extract relevant source temperature sentences; where no separate region is named, the map and full discussion remain available.

Map image bytes are fetched and saved with each outlook snapshot. They must have GIF/PNG signatures and remain within a 5 MiB limit. Historical/cache views display the stored image, never the mutable operational image URL. Source links remain available. If an image fails, the map is unavailable with a warning, unless a previously saved map has exactly the same outlook name and issue date. An older map is never attached to a newly dated outlook.

CPC's operational Weeks 3–4 outlook is the free authoritative subseasonal substitute for ingesting and calibrating separate raw SubX hindcast/forecast archives. This V1 does not claim to download raw SubX fields. The connector extracts the temperature category definition from the actual retrieved product-page legend; when that text is absent it says “See official legend” rather than assuming a category scheme. The Weeks 3–4 page checked during development explicitly listed three temperature categories (above, near, and below normal) and probabilities above 33%. Older linked FAQ text still described two categories, so it is not used to override the current product. These are probabilities for a **period mean**, not deterministic daily temperatures or HDD forecasts. A warm period mean does not exclude shorter cold episodes. Europe is outside these U.S. outlooks.

## Rutgers Global Snow Lab

- [Weekly Eurasian extent text file](https://climate.rutgers.edu/snowcover/files/wkcov.eurasia.txt).
- [Download directory and unit documentation](https://climate.rutgers.edu/snowcover/table_area.php?ui_set=2&ui_sort=0).
- [Snow-cover record methodology](https://climate.rutgers.edu/snowcover/docs.php?target=vis).

Input is year, Rutgers week number, and square kilometers. Divide by 1,000,000 for million km². Compare the same Rutgers week across 1991–2020 for mean, 10th/90th quantiles, and midpoint empirical percentile. Seasonal charts preserve Rutgers week numbers; these are **not ISO weeks**. The exact latest period start/end comes from its official weekly chart, rather than an assumed calendar conversion. One/four-week changes require the corresponding source week in the same year; a missing observation or a year-boundary comparison remains unavailable in V1.

The data represent Eurasia, not a custom Siberia mask. The record supplies continental snow-cover extent, not snow depth or water equivalent. October/fall accumulation is contextual; snow does not mechanically guarantee U.S. cold. Rutgers publication can lag, which is shown explicitly. Current charts compare the latest year against five preceding years and a fixed 1991–2020 baseline.

## NOAA/NSIDC Arctic sea ice

- [Daily Arctic Sea Ice Index v4 CSV](https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv).
- [Dataset and version documentation](https://nsidc.org/data/g02135/versions/4).
- [Official data archive](https://nsidc.org/data/seaice_index/data-and-image-archive).

Citation: Fetterer and colleagues (2025), **Sea Ice Index, Version 4**, NOAA/NSIDC, [DOI 10.7265/a98x-0f50](https://doi.org/10.7265/a98x-0f50), Arctic daily extent subset.

Input extent is already million km². Extent counts grid-cell area above the 15% ice-concentration threshold; it is not ice area or volume. Negative sentinels and records with missing coverage are excluded. Recent values are provisional; Version 4 incorporates AMSR2.

This application computes a **1991–2020 same-month/day** baseline, distinct from NSIDC's published 1981–2010 climatology. It calculates normal, anomaly, and midpoint empirical percentile from those same-day observations. February 29 uses only actual leap-year observations. Seasonal x-values map month/day onto year 2000 so leap years do not shift March–December comparisons. Charts include the latest year, two preceding years, and 2012. Regional ice grids are outside V1; total Arctic extent is secondary context with no direct gas-demand conversion.

## Validation performed

Actual HTTPS GET requests succeeded for the two NAO CSVs, all three CPC product pages and discussion, Rutgers weekly series and dated chart, and NSIDC v4 CSV. Image URLs were also verified as actual image responses. At the development pull on September 15, 2026 UTC: NAO observation September 12; GEFS initialization September 14 with 31 members and leads 0–15 days; CPC issues September 14 and September 11; Rutgers week 35 ending August 31; NSIDC September 13. Dates are evidence of that validation run, not hard-coded application inputs.

Tests exercise valid-date forecast alignment, missing forecast tails, schema failures, invalid calendar dates, temperature versus precipitation categories, snow unit conversion, same-week baseline selection, missing snow weeks, sea-ice unit preservation, missing-value rejection, and leap-calendar alignment.
