# Gas Weather: a beginner’s guide

## Start with one question

**Will the weather make people need more heating or air conditioning—and has that expectation changed?**

Cold weather can increase gas use for heating. Hot weather can increase air-conditioning electricity use; gas-fired power plants may burn more gas to supply it. Mild weather can reduce both needs. “Power burn” means gas consumed to generate electricity. The mix of power plants matters, so extra cooling does not translate into a fixed amount of gas everywhere. [EIA explains the weather connection](https://www.eia.gov/energyexplained/natural-gas/factors-affecting-natural-gas-prices.php).

## Your two-minute routine

1. **Read “The simple read.”** Overview starts with a short explanation of whether weather points to more or less gas use than usual.
2. **Look at the four maps just below it.** Check where warmth or cold is favored, and read each map's issue and valid dates.
3. **Read the short polar-vortex guide.** It explains clues to a possible cold spell and what the current winter watch can tell you.
4. **Check the demand details below.** Heating and cooling can offset each other. Then compare the new forecast with an older forecast for the same future dates.
5. **Check Gas market for storage.** Weather is one part of the market picture.

“Issued” tells you when a forecast was made; “valid” tells you which future days it describes. “Retrieved” tells you when this app downloaded it. Refreshing cannot make an old forecast new.

## Heating and cooling “points”

The dashboard counts **degree days**, which measure how far a daily average temperature is from a standard 65°F reference. A degree day is a temperature measure accumulated over time, not one calendar day or a thermostat recommendation.

| Daily average | Heating degree days (HDD) | Cooling degree days (CDD) |
| --- | ---: | ---: |
| 55°F | 10 | 0 |
| 65°F | 0 | 0 |
| 75°F | 0 | 10 |

More HDD means more heating need; more CDD means more cooling need. Daily values add together: three days with 10 HDD each total 30 HDD. [EIA’s degree-day guide](https://www.eia.gov/energyexplained/units-and-calculators/degree-days.php).

“Population weighted” means regions with more people count more. This dashboard approximates the Lower 48 states and DC using eight regional stations. It cannot describe every neighborhood, building, or power grid.

## Two different comparisons

**Versus normal** compares the forecast with the historical 1991–2020 average for those dates. “Anomaly” simply means this difference. Normal is a seasonal reference, not a promise of what should happen.

**Versus the earlier forecast** measures a revision: what the weather model changed its mind about. A “model run” is a new forecast calculation. For example, a forecast can remain colder than normal while becoming warmer than yesterday’s forecast. Both statements can be true.

Only shared dates count in revisions. A 14-day comparison and a 15-day forecast total cover different periods. A dash means unavailable, not zero.

## What the gas estimate means

**Bcf** means billion cubic feet of gas. **Bcf/d** means that amount per day. Positive estimated demand means more gas use relative to the selected comparison; negative means less.

The calculation multiplies heating and cooling differences by separate, editable assumptions, then adds the results. For example, an assumed 0.5 Bcf per cooling degree day converts an extra 2 daily CDD into an estimated +1 Bcf/d.

**These coefficients are illustrative: they have not been fitted or validated against observed gas consumption.** The result is a scenario estimate of a weather-related difference. It is neither measured consumption nor total national gas demand. Changing the assumptions changes the estimate, even when the forecast stays identical.

## How to read the longer-range maps

The four maps near the top of Overview have different clocks:

- **6–10 days and 8–14 days:** yesterday's NOAA forecasts. “Yesterday” follows the Eastern Time calendar.
- **Weeks 3–4:** the latest weekly forecast available by yesterday. It is issued weekly, so its issue date can be several days earlier.
- **November–January:** NOAA's latest available outlook for that whole three-month season. As of September 15, 2026, this means **November 2026–January 2027**. It is one seasonal average, not a separate prediction for every month.

The actual dates appear with each picture. For current short-range outlooks and a fuller reading guide, open **Longer-range outlook**. [Map sources and date rules](noaa_maps.md).

“Subseasonal” means the coming weeks. NOAA’s Climate Prediction Center (CPC) maps describe the average across the labeled period. Red favors warmer-than-normal conditions; blue favors colder-than-normal conditions.

A 40% chance of above-normal temperatures means a 40% chance of landing in the warmest third of the historical range. The remaining chance covers near-normal and below-normal conditions. It does not mean 40 degrees warmer. **EC** means equal chances, not guaranteed average weather. A warm period can still contain cold days. [CPC’s outlook explanation](https://www.cpc.ncep.noaa.gov/products/predictions/WK34/).

## What is the polar vortex?

The **stratospheric polar vortex** is a large circulation of winds high above the Arctic that normally exists in winter. The question is whether it becomes disrupted, rather than whether a vortex appears. Changes high above the Arctic can sometimes affect the weather below and help cold air move south.

The overview's guide explains clues such as weakening high-altitude winds, rapid warming high above the Arctic, and persistent weather patterns that can steer cold air. Its winter-watch status is a clue, not a probability that your region will turn cold. The **Cold-weather clues** page has the supporting charts and more explanation.

## The other panels

**Polar vortex and NAO:** large-scale circulation clues; they do not guarantee a cold event where gas is consumed. **Snow and sea ice:** background context, with no direct gas conversion. **Storage:** a reserve of available gas; a build adds gas and a draw removes it. **Henry Hub spot:** a physical-market gas price, distinct from a futures contract.

Use the dashboard to understand weather and its possible demand effects. A higher demand estimate does not predict a higher gas price: supply, storage, exports, and competing fuels also matter. This is a learning and research tool, not trading advice. [EIA’s price-factor guide](https://www.eia.gov/energyexplained/natural-gas/factors-affecting-natural-gas-prices.php).

Use **Update the data** for a fresh check. The homepage maps also check whether “yesterday” has changed when the app reruns. Simply leaving the page open does not start a background refresh schedule.
