# EIA natural gas fundamentals

This connector uses free, official EIA workbook downloads without an API key.

| Series | Units | Data | Download |
| --- | --- | --- | --- |
| Henry Hub daily physical spot price (`RNGWHHD`) | USD per million Btu (`USD/MMBtu`) | [Daily series](https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm) | [XLS](https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls) |
| Lower 48 working natural gas in underground storage (`NW2_EPG0_SWO_R48_BCF`) | Billion cubic feet (`Bcf`) | [Weekly series](https://www.eia.gov/dnav/ng/hist/nw2_epg0_swo_r48_bcfw.htm) | [XLS](https://www.eia.gov/dnav/ng/hist_xls/NW2_EPG0_SWO_R48_BCFw.xls) |

Henry Hub is **spot, not a futures price**, settlement, or a live tradable quote. The series has reporting delays. Holiday and missing dates are omitted; the connector does not manufacture or carry forward observations. Price history begins in 1997 and storage history in 2010, as available in the published workbooks. The source headers and units are validated before observations enter the dashboard.

## Time and freshness

Every observation retains its source date: the price observation date or the storage reporting week end. Each workbook's `Contents` sheet supplies its separate release date. `observed_at`, `price_observed_at`, and `storage_observed_at` are release dates normalized to midnight UTC for machine comparison; their precision is **a date, not an asserted intraday publication time**. `observed_at` uses the later of the two series release dates. The per-series dates should be shown as well, because one fresh series does not make the other fresh. If release metadata is missing, the corresponding latest data date is used with a warning.

The connector refreshes when the application's EIA cache refreshes. Storage normally updates weekly; [EIA's report](https://ir.eia.gov/ngs/ngs.html) includes the release schedule and exceptions. Repeated downloads within a day may return identical values. The application's persistent cache retains the previous complete successful result if either download or validation fails. Downloads use bounded connection/read timeouts and two retries for transient failures.

## Storage comparison

For each target reporting date:

1. Use the five completed calendar years immediately before the target date's year. For a 2026 observation, these are 2021–2025.
2. Find each prior year's observation closest to the target month and day, within seven calendar days and within that same calendar year. Most matches are within three days; the seven-day allowance accommodates the first/last reporting week of a year. Ties select the earlier date. February 29 maps to February 28 in a non-leap year.
3. Require an observation from all five years. Calculate their arithmetic mean, minimum, and maximum. Missing years yield unavailable benchmark values rather than a silently shortened sample.
4. Report the current stock minus this mean in Bcf and as a percentage of the mean.

Each row exposes the five comparison years and the exact selected dates/values, so the benchmark can be audited. This is a **locally calculated seasonal comparison** and may differ from EIA's published five-year average/range. Historical rows use the five calendar years before each row's year, without using the current row's year or future years. Downloaded historical observations incorporate EIA revisions; these are not vintage historical estimates or a point-in-time backtest dataset.

The latest weekly change is current stock less the preceding stock, only when observations are exactly seven days apart. Positive means a reported stock build; negative means a draw. Missing weeks produce an unavailable weekly change. Stock differences include reclassifications between base and working gas and may differ from EIA's adjusted net injection/withdrawal. See [EIA storage definitions and notes](https://www.eia.gov/dnav/ng/TblDefs/ng_stor_wkly_tbldef.asp).

## Python interface

`data_sources.eia.fetch_eia()` returns a JSON-serializable dictionary containing:

- `observed_at`, `timestamp_precision`, `source_url`, `methodology`, and `warnings`.
- Separate `price_*` and `storage_*` values for `source_url`, `download_url`, `observed_at`, `release_date`, and `data_date`.
- `price_label`: `Henry Hub daily spot (not futures)`.
- `price_rows`: date-ascending `{date, price_usd_mmbtu}` observations; `latest_price` repeats the final row.
- `storage_rows`: date-ascending observations; `latest_storage` repeats the final row. Fields are `date`, `storage_bcf`, `weekly_change_bcf`, `five_year_avg`, `five_year_min`, `five_year_max`, `surplus_bcf`, `surplus_pct`, `comparison_years`, `comparison_sample_count`, and `comparison_observations`.

Absent calculations are JSON `null`, never NaN, zero replacements, or fabricated data. Errors propagate to the application's last-successful-result cache.
