# NOAA temperature maps at the top of the dashboard

The overview shows four saved NOAA Climate Prediction Center images:

1. The previous day's **6–10 day** temperature outlook.
2. The previous day's **8–14 day** temperature outlook.
3. The **Weeks 3–4** outlook available as of that previous day. NOAA normally publishes this on Friday, so its issue date is usually older than yesterday.
4. The **most recently issued November–December–January seasonal outlook**. This is a three-month average outlook, updated monthly. It is not three separate monthly forecasts and is not described as yesterday's issue.

“Previous day” follows the calendar in **America/New_York**, where CPC publishes its products. This includes Eastern daylight/standard time changes. Cached selection must be reconsidered at Eastern midnight. In January the seasonal target retains the November–January period already underway; from February onward it selects the coming November–January period. The payload exposes `requested_previous_date`, `requested_season`, `season_start`, and `season_end` for cache checks.

## Free official sources

- [NOAA daily outlook archive selector](https://www.cpc.ncep.noaa.gov/products/archives/short_range/srarc.ind.php). Its submitted form links dated image and discussion files. The connector uses those documented dated paths directly with GET requests; it does not need a form submission at runtime.
- [NOAA Weeks 3–4 archive](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/archives/). Its calendar builds `YYYY/MM/DD/WK34temp.gif` and `week34fcst.txt` links for Friday issues.
- [NOAA current seasonal outlook selector](https://www.cpc.ncep.noaa.gov/products/predictions/long_range/seasonal.php) and [seasonal discussion](https://www.cpc.ncep.noaa.gov/products/predictions/long_range/fxus05.html).
- [NOAA monthly/seasonal issue schedule](https://www.cpc.ncep.noaa.gov/products/predictions/schedule.html).

### Historical map safeguards

Daily maps come from `.../products/archives/short_range/YYYY/MM/DD/610temp.YYYYMMDD.fcst.gif` and the equivalent `814temp` path. The date in the associated `PMDMRD.YYYYMMDD.txt` forecaster dateline must exactly match the requested date. The written valid dates must agree with the appropriate 6–10 or 8–14 day range. The connector never substitutes today's mutable map when yesterday's archive is missing.

Weeks 3–4 uses the latest scheduled Friday on or before yesterday. Its archived discussion must match that Friday and its 14-day valid window must start 15 days after the issue. If the scheduled archive cannot be retrieved, the connector can check two preceding Fridays. An older fallback keeps its actual date, carries `is_expected_weekly_issue=False`, and creates an explicit warning that a newer map may exist at NOAA. No future issue can be labeled historical.

### Seasonal snapshot safeguards

The connector resolves the target NDJ season from NOAA's actual navigation link text; it does not hard-code a lead number. It then verifies that the *selected forecast heading* is Nov–Dec–Jan of the requested years. A navigation link mentioning NDJ is not sufficient evidence that the displayed map is NDJ.

The issue date comes from NOAA's seasonal forecaster dateline. A future issue is rejected. The saved image comes from the selected official temperature image link. After download, the connector re-reads the issue and selected-period metadata to reject publication rollovers during the request. The image bytes and metadata are stored together, so the UI never replaces a cached image with the mutable live URL. The seasonal map is identified as an operational snapshot, not a dated archive.

This check verifies the accompanying NOAA issue/period metadata; it does not perform automatic optical character recognition of image labels. The current release's image labels were also visually checked during development. The source URLs remain available so the reader can inspect NOAA's originals.

Every image is signature-checked, limited to 5 MiB, and decoded/verified as an actual GIF or PNG. HTML error pages and truncated images are rejected. Each product can fail independently. Missing images stay missing, with a warning; no illustrative map is generated. Returned dictionaries contain JSON-safe values, image bytes encoded as base64, and date precision explicitly marked.

## Verified live retrieval — September 15, 2026

The new connector retrieved and decoded all four products without warnings at 14:11 UTC:

| Product | Issued | Valid period | Saved image size |
| --- | --- | --- | --- |
| 6–10 day | Sep 14, 2026 | Sep 20–24, 2026 | 300,893 bytes |
| 8–14 day | Sep 14, 2026 | Sep 22–28, 2026 | 284,557 bytes |
| Weeks 3–4 | Sep 11, 2026 | Sep 26–Oct 9, 2026 | 253,449 bytes |
| Nov–Dec–Jan | Aug 20, 2026 | Nov 2026–Jan 2027 | 231,081 bytes |

The NDJ image's printed labels were visually confirmed as “Nov-Dec-Jan 2026-27” and “August 20, 2026.” Twenty offline tests cover Eastern calendar boundaries, year crossings, source parsing, selecting the right season, future issue rejection, changed metadata during download, partial outages, weekly fallback labeling, and invalid images.
