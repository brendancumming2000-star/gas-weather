"""Plain-language context views, with source detail available on demand.

Views accept cached source payloads and never fetch or infer missing observations.
Outlook maps are the image bytes saved with their issue, not mutable live URLs.
"""
from __future__ import annotations

import base64
import binascii
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.charts import AMBER, BLUE, GREEN, MUTED, line_chart, style
from models.signals import vortex_risk
from storage.database import parse_time, utcnow


def _number(value, digits=1, signed=False, suffix=""):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not math.isfinite(number):
        return "Unavailable"
    return f"{number:{'+' if signed else ''},.{digits}f}{suffix}"


def _date(value):
    if not value:
        return "date unavailable"
    try:
        parsed = parse_time(value)
        return parsed.strftime("%b %d, %Y" if len(str(value)) == 10 else "%b %d, %Y · %H:%M UTC")
    except (TypeError, ValueError):
        return "date unavailable"


def _age_hours(value):
    try:
        return (utcnow() - parse_time(value)).total_seconds() / 3600 if value else None
    except (TypeError, ValueError):
        return None


def _frame(rows, required):
    frame = pd.DataFrame(rows or [])
    return frame if set(required).issubset(frame.columns) else pd.DataFrame()


def _chart(fig, key):
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False})


def _warnings(payload):
    for warning in dict.fromkeys(payload.get("warnings") or []):
        st.warning(str(warning))


def _source_details(payload, label, extra=""):
    source = payload.get("source_page") or payload.get("source_url")
    if source:
        st.markdown(f"[{label}]({source})")
    _warnings(payload)
    if payload.get("methodology") or extra:
        with st.expander(f"Source and calculation details · {label}"):
            if extra:
                st.write(extra)
            if payload.get("methodology"):
                st.write(payload["methodology"])
            if payload.get("source_url") and payload.get("source_url") != source:
                st.markdown(f"[Download original data]({payload['source_url']})")


def _season_note():
    month = utcnow().month
    if month in (12, 1, 2):
        return "Winter lens: colder weather can increase heating use. Warmer weather can reduce it; warm southern areas can still need air conditioning."
    if month in (6, 7, 8):
        return "Summer lens: hotter weather can increase air-conditioning use and gas burned to generate electricity. Cooler weather can reduce that demand."
    return "Spring/fall lens: some regions can need heating while others need air conditioning. Check both demand measures before deciding what a warmer or cooler outlook means."


def render_outlooks(cpc):
    cpc = cpc or {}
    st.write("These maps from NOAA’s Climate Prediction Center (CPC) show the odds of a period being warmer or cooler than usual for that time of year. “Subseasonal” simply means looking a few weeks ahead.")
    a, b, c = st.columns(3)
    a.markdown("**6–10 days**  \nA look at the period just beyond the coming week.")
    b.markdown("**8–14 days**  \nThe second week ahead. It overlaps the 6–10 day outlook.")
    c.markdown("**Weeks 3–4**  \nThe broader pattern beyond the daily forecast.")

    outlooks = {o.get("name"): o for o in cpc.get("outlooks", []) if isinstance(o, dict)}
    choices = ["6–10 day", "8–14 day", "Weeks 3–4"]
    chosen = st.radio("Choose a forecast window", choices, index=2, horizontal=True, key="context_outlook_horizon")
    outlook = outlooks.get(chosen)
    for name in choices:
        if name not in outlooks:
            st.caption(f"{name}: source product unavailable.")

    map_col, guide_col = st.columns([1.8, 1], gap="large")
    with map_col:
        if not outlook:
            st.info("This outlook is unavailable. Choose another window or refresh the sources.")
        else:
            st.markdown(f"### {chosen} temperature outlook")
            st.caption(f"Issued {_date(outlook.get('observed_at'))}  •  Covers {outlook.get('valid_period') or 'dates shown on the official map'}")
            age = _age_hours(outlook.get("observed_at"))
            if age is None:
                st.warning("The issue date is missing, so the age of this outlook cannot be checked.")
            elif age > 24 * (10 if chosen == "Weeks 3–4" else 3):
                st.warning("This saved outlook is older than the expected update window. Check the dates before using it.")
            if outlook.get("image_base64"):
                try:
                    st.image(base64.b64decode(outlook["image_base64"], validate=True), width="stretch")
                except (binascii.Error, ValueError, TypeError, OSError):
                    st.info("The saved map cannot be displayed. Use the official outlook below.")
            else:
                st.info("A map snapshot is unavailable for this issue. The official outlook link remains available below.")
            if outlook.get("source_url"):
                st.markdown(f"[Open the official outlook and its legend]({outlook['source_url']})")

    with guide_col:
        st.markdown("### How to read the map")
        st.markdown("**Orange / red:** warmer than usual is favored.  \n**Blue:** cooler than usual is favored.  \n**N:** near-normal temperatures are favored.  \n**EC:** equal chances; no category is favored.")
        st.write("The colors describe temperature, not rain or a gas-price forecast. The official outlook link opens the legend for this particular map.")
        st.markdown("**A 50% label means a 50% chance of the marked temperature category.** It does not mean 50% warmer, or a 50% chance that gas prices rise.")
        st.caption("The outlook averages the whole labeled period. A warm two-week average can still contain a few cold days. More distant outlooks cannot tell you the exact temperature on a particular day.")

    st.info(_season_note())
    st.caption("Gas-demand interpretation: heating and cooling can pull in opposite directions. The maps do not give enough information to calculate degree days or gas volume; use Heating & cooling for those estimates.")
    if outlook:
        with st.expander("Regional detail and the official explanation"):
            st.markdown("**The category definition from this saved product**")
            st.write(outlook.get("category_definition") or "See the official map legend; a category definition was not available in the saved product.")
            summaries = [r for r in outlook.get("regional_summary", []) if isinstance(r, dict)]
            for region in summaries:
                st.markdown(f"**{region.get('region', 'Region')}** — {region.get('summary') or 'Summary unavailable.'}")
            if outlook.get("state_categories"):
                st.caption("State counts describe how many listed states fall into each category. They are not a population-weighted regional probability.")
            if outlook.get("discussion"):
                st.markdown("**CPC’s full discussion**")
                st.write(outlook["discussion"])
            if outlook.get("discussion_url"):
                st.markdown(f"[CPC forecast discussion]({outlook['discussion_url']})")
        _warnings(outlook)
    _warnings(cpc)
    st.caption("These outlooks cover the United States. Weeks 3–4 uses CPC’s official product; separate raw SubX model data and European temperature outlooks are not included.")


def _render_vortex(gfs):
    st.markdown("### 1. Winds high above the Arctic")
    st.write("The **jet stream** is a fast-moving band of wind that helps steer everyday weather. The **stratospheric polar vortex** is a larger circulation much higher above the Arctic. They can interact, but they are different parts of the atmosphere.")
    st.write("In winter, major changes in those high-altitude winds can sometimes influence weather below. They are an early clue to watch, not a forecast of a cold snap in your region.")
    pv = gfs.get("polar_vortex") or {}
    rows = _frame(pv.get("rows"), ["date", "u10_ms"])
    age = _age_hours(gfs.get("model_run") or gfs.get("observed_at"))
    label, note = vortex_risk(pv)
    if age is None or age > 18:
        st.info("A current high-altitude forecast is unavailable. Any saved measurements below are historical context.")
    elif label == "Unclassified":
        st.info("Outside the winter watch period. The dashboard does not interpret ordinary summer wind changes as a winter cold signal.")
    elif label == "Moderate":
        initial_wind = pd.to_numeric(rows.u10_ms, errors="coerce").iloc[0]
        if initial_wind < 0:
            st.info("Unusual winter wind direction is already present at the start of the forecast: winds blow east to west. This is an existing condition, not a newly forecast reversal. Its effect on U.S. temperatures remains uncertain.")
        elif initial_wind > 0 and pv.get("winter_westerly_to_easterly_transition", True):
            st.info("Winter wind-reversal clue: winds start west to east, then turn east to west in the sampled forecast. Its effect on U.S. temperatures remains uncertain.")
        else:
            st.info("Some sampled winter winds blow east to west, opposite their usual direction. The data do not establish a new reversal or predict where cold air will arrive.")
    elif label == "Low":
        st.info("No winter wind reversal in the sampled forecast. Cold spells can still develop through other weather patterns.")
    else:
        st.info("There is not enough high-altitude data for a winter watch assessment.")
    st.caption(f"Forecast issued {_date(gfs.get('model_run'))}. [NOAA: the polar vortex and the jet stream](https://www.climate.gov/news-features/understanding-climate/understanding-arctic-polar-vortex)")
    if not rows.empty:
        with st.expander("Explore the high-altitude wind and temperature charts"):
            st.write("The wind line measures average west-to-east wind around 60°N, at the 10 hPa pressure level high in the stratosphere. Positive values mean west-to-east flow; below zero means the wind blows east to west. m/s means meters per second.")
            wind = line_chart(rows, "date", "u10_ms", "High-altitude wind · meters/second", GREEN)
            wind.add_hline(y=0, line_dash="dot", line_color=AMBER)
            _chart(wind, "context_vortex_wind")
            if "temp10_k" in rows:
                temperatures = rows.assign(temp10_c=pd.to_numeric(rows.temp10_k, errors="coerce") - 273.15)
                st.write("This temperature is high above the Arctic, not at ground level. A rise here does not directly tell us how cold U.S. cities will get.")
                _chart(line_chart(temperatures, "date", "temp10_c", "High-altitude Arctic temperature · °C", AMBER), "context_vortex_temperature")
            st.caption(note)
            st.caption("One model forecast and an average around the Arctic cannot establish the location or probability of a U.S. cold outbreak. Historical vortex percentiles and displacement diagnostics are not included.")
            st.dataframe(rows, hide_index=True, width="stretch")
    _source_details(pv, "NOAA high-altitude data")


def _render_nao(cpc):
    st.markdown("### 2. A weather-pattern clue over the North Atlantic")
    st.write("**NAO** means North Atlantic Oscillation. It is a number describing a large-scale pressure pattern over the Atlantic. A negative NAO can accompany persistent high pressure near Greenland, called **blocking**, which can redirect the usual flow of weather.")
    st.write("That setup can favor cold in parts of eastern North America or Europe, especially in winter. The location of the block and weather over the Pacific also matter, so NAO alone cannot tell us where cold air will arrive.")
    nao = cpc.get("nao") or {}
    future = nao.get("forecast_mean_days8_15")
    age = _age_hours(nao.get("forecast_initialized_at"))
    if age is None or age > 48 or _number(future) == "Unavailable":
        st.info("A current NAO forecast is unavailable. Any saved chart below retains its original dates.")
    else:
        direction = "negative" if float(future) < 0 else "positive" if float(future) > 0 else "near zero"
        st.info(f"The average forecast for days 8–15 is {direction} ({float(future):+.2f}). This is a weather-pattern index, not a temperature or a cold-outbreak probability.")
    st.caption(f"Forecast issued {_date(nao.get('forecast_initialized_at'))}  •  Latest observation {_date(nao.get('observed_at'))}: {_number(nao.get('value'), 2, True)}")
    observation_age = _age_hours(nao.get("observed_at"))
    if observation_age is not None and observation_age > 96:
        st.warning("The observed NAO value is old. Its date above is separate from the forecast’s issue date.")
    history = _frame(nao.get("history"), ["date", "value"])
    ensemble = _frame(nao.get("forecast"), ["date", "mean"])
    if not history.empty or not ensemble.empty:
        with st.expander("Explore the Atlantic-pattern charts"):
            if not ensemble.empty:
                st.write("The blue line is the average of many model forecasts, called an **ensemble**. A wider shaded band means those forecasts disagree more. The band is not a guaranteed range or a calibrated probability of cold.")
                fig = go.Figure()
                if {"p10", "p90"}.issubset(ensemble.columns):
                    fig.add_trace(go.Scatter(x=ensemble.date, y=ensemble.p90, line=dict(width=0), showlegend=False, hoverinfo="skip"))
                    fig.add_trace(go.Scatter(x=ensemble.date, y=ensemble.p10, line=dict(width=0), fill="tonexty", fillcolor="rgba(117,169,255,.15)", name="Middle 80% of model values"))
                fig.add_trace(go.Scatter(x=ensemble.date, y=ensemble["mean"], name="Average model forecast", line=dict(color=BLUE, width=3)))
                if "prior_mean" in ensemble:
                    fig.add_trace(go.Scatter(x=ensemble.date, y=ensemble.prior_mean, name="Previous forecast", line=dict(color=MUTED, dash="dot")))
                fig.add_hline(y=0, line_color=AMBER, line_dash="dot")
                fig.update_yaxes(title="NAO index · no temperature units")
                _chart(style(fig, 310), "context_nao_forecast")
            if not history.empty:
                st.caption("Recent measured NAO: above zero and below zero are opposite phases of the Atlantic pressure pattern.")
                _chart(line_chart(history.tail(365), "date", "value", "Observed NAO index"), "context_nao_history")
            if _number(nao.get("percentile")) != "Unavailable":
                st.caption(f"Latest observation’s historical percentile: {_number(nao.get('percentile'), 0)}. This ranks it among past observations; it is not a chance of cold. Baseline: {nao.get('baseline', 'unavailable')}.")
    _source_details(nao, "CPC North Atlantic Oscillation data", nao.get("forecast_methodology", ""))


def _seasonal_chart(payload, source):
    x = "week" if source == "snow" else "day_of_year"
    seasonal = _frame(payload.get("seasonal"), [x, "year", "extent_million_km2"])
    clim = _frame(payload.get("climatology"), [x, "mean"])
    if seasonal.empty:
        st.info("Seasonal chart observations are unavailable.")
        return
    st.write("The bright green line is the latest year in the data. The dotted line is the 1991–2020 average at the same time of year. The shaded band spans the middle 80% of those historical values, when available.")
    fig = go.Figure()
    if not clim.empty:
        if {"p10", "p90"}.issubset(clim.columns):
            fig.add_trace(go.Scatter(x=clim[x], y=clim.p90, line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=clim[x], y=clim.p10, line=dict(width=0), fill="tonexty", fillcolor="rgba(117,169,255,.10)", name="Middle 80% of historical values"))
        fig.add_trace(go.Scatter(x=clim[x], y=clim["mean"], line=dict(color=MUTED, dash="dot"), name="1991–2020 average"))
    years = sorted(seasonal.year.dropna().unique())
    for year in years:
        points = seasonal[seasonal.year == year].sort_values(x)
        fig.add_trace(go.Scatter(x=points[x], y=points.extent_million_km2, name=str(year), line=dict(color=GREEN if year == max(years) else None, width=3 if year == max(years) else 1)))
    fig.update_yaxes(title="Area · million square kilometers")
    fig = style(fig, 330)
    if source == "ice":
        fig.update_xaxes(tickvals=[1, 61, 122, 183, 245, 306], ticktext=["Jan", "Mar", "May", "Jul", "Sep", "Nov"])
    else:
        fig.update_xaxes(title="Week of year in the Rutgers record")
    _chart(fig, f"context_{source}_seasonal")
    st.caption(payload.get("baseline", "Historical comparison period unavailable."))
    st.caption(f"Historical percentile: {_number(payload.get('percentile'), 0)}. The 20th percentile, for example, means the observation is around the low end of past values for this season; it does not mean a 20% chance of cold.")


def _render_snow_ice(snow, ice):
    st.markdown("### 3. Snow and sea ice: seasonal background")
    st.write("Snow on land and ice on the ocean help describe conditions around the Arctic. Their relationship with later U.S. weather is complex. Neither is proof of an approaching cold winter, and neither is converted into gas demand here.")
    columns = st.columns(2, gap="large")
    for col, source, payload, title in [(columns[0], "snow", snow, "Snow across Europe and Asia"), (columns[1], "ice", ice, "Sea ice across the Arctic Ocean")]:
        with col:
            st.markdown(f"**{title}**")
            st.caption("Eurasia means Europe and Asia. This measures the area covered by snow, not snow depth." if source == "snow" else "Sea ice forms from frozen seawater. “Extent” counts ocean areas with at least 15% ice cover; it does not measure ice thickness.")
            if not payload:
                st.info("Source observations are unavailable.")
                continue
            st.metric("Area covered", _number(payload.get("current_extent_million_km2"), 2, suffix=" million km²"))
            st.write(f"**Difference from usual:** {_number(payload.get('anomaly_million_km2'), 2, True, ' million km²')}")
            st.caption("Positive = more area covered than usual; negative = less. 1 million km² means one million square kilometers.")
            if source == "snow":
                st.caption(f"Observation week: {_date(payload.get('period_start'))} to {_date(payload.get('period_end') or payload.get('observed_at'))}")
            else:
                st.caption(f"Observation: {_date(payload.get('observed_at'))}. Recent sea-ice values may be revised.")
            age = _age_hours(payload.get("observed_at"))
            if age is None:
                st.warning("The observation date is missing; freshness cannot be checked.")
            elif age > 24 * (10 if source == "snow" else 5):
                st.warning("This observation is old. It describes the dated period above, not today’s conditions.")
            with st.expander(f"Compare {source} with previous years"):
                _seasonal_chart(payload, source)
                if source == "snow":
                    st.caption(f"Four-week change: {_number(payload.get('change_4w'), 2, True, ' million km²')}. Missing comparison weeks remain unavailable.")
            _source_details(payload, "Rutgers snow-cover data" if source == "snow" else "NSIDC sea-ice data")


def render_cold_context(gfs, cpc, snow, ice):
    st.subheader("Why might the cold-weather outlook change?")
    st.write("Start with the temperature forecast and heating demand. The clues here add background, especially in winter; they do not tell us how much gas people will use on their own.")
    _render_vortex(gfs or {})
    st.divider()
    _render_nao(cpc or {})
    st.divider()
    _render_snow_ice(snow or {}, ice or {})


def render_market(eia):
    eia = eia or {}
    st.subheader("Weather is one part of the gas market")
    st.write("Heating and air conditioning change energy demand. Supply, stored gas, exports and what traders already expect also affect prices. These two series put the weather into context.")
    st.caption("[EIA explains how weather and storage affect the gas market](https://www.eia.gov/energyexplained/natural-gas/factors-affecting-natural-gas-prices.php)")
    prices = _frame(eia.get("price_rows"), ["date", "price_usd_mmbtu"])
    stocks = _frame(eia.get("storage_rows"), ["date", "storage_bcf"])
    p = prices.iloc[-1].to_dict() if not prices.empty else eia.get("latest_price") or {}
    s = stocks.iloc[-1].to_dict() if not stocks.empty else eia.get("latest_storage") or {}

    st.markdown("### 1. The price of gas for near-term delivery")
    st.write("**Henry Hub** is a major U.S. natural-gas trading location. Its **spot price** is a benchmark for physical gas delivered soon. **$/MMBtu** means dollars per one million British thermal units—a measure of energy.")
    if _number(p.get("price_usd_mmbtu")) != "Unavailable":
        st.metric("Henry Hub daily spot price", f"${_number(p['price_usd_mmbtu'], 2)} / MMBtu")
        release = eia.get("price_release_date") or eia.get("price_observed_at")
        st.caption(f"Price date: {_date(p.get('date'))}  •  EIA release: {_date(str(release)[:10] if release else None)}")
        price_age = _age_hours(release or p.get("date"))
        if price_age is not None and price_age > 24 * 10:
            st.warning("This saved price series is old. It remains visible for context with its original date.")
        if not prices.empty:
            st.caption("Read the line as the reported price over time. This is a delayed daily observation; futures contracts and live quotes can show different prices.")
            _chart(line_chart(prices.tail(260), "date", "price_usd_mmbtu", "Price · dollars per MMBtu", AMBER, 290), "context_gas_price")
    else:
        st.info("The latest spot-price observation is unavailable.")
    if eia.get("price_source_url"):
        st.markdown(f"[EIA Henry Hub price history]({eia['price_source_url']})")

    st.markdown("### 2. How much gas is stored for later?")
    st.write("**Working gas in storage** is gas held underground that can be withdrawn for use. It provides a buffer when demand rises. **Bcf** means one billion cubic feet of gas; **Bcf/day** means that volume used or moved in one day.")
    if _number(s.get("storage_bcf")) != "Unavailable":
        a, b, c = st.columns(3)
        a.metric("Gas in storage · Lower 48", _number(s.get("storage_bcf"), 0, suffix=" Bcf"))
        change = s.get("weekly_change_bcf")
        if _number(change) == "Unavailable":
            b.metric("Change over the last week", "Unavailable")
        else:
            b.metric("Change over the last week", f"{_number(abs(float(change)), 0)} Bcf {'added' if float(change) > 0 else 'removed' if float(change) < 0 else 'change'}")
        c.metric("Compared with usual for this season", _number(s.get("surplus_bcf"), 0, True, " Bcf"))
        release = eia.get("storage_release_date") or eia.get("storage_observed_at")
        st.caption(f"Storage week ending: {_date(s.get('date'))}  •  EIA release: {_date(str(release)[:10] if release else None)}")
        storage_age = _age_hours(release or s.get("date"))
        if storage_age is not None and storage_age > 24 * 10:
            st.warning("This saved storage series is old. Compare its reporting week with the dates of the weather forecast.")
        st.markdown("A **build** means the reported amount in storage increased. A **draw** means it decreased. A **surplus** means more gas than the seasonal comparison; a **deficit** means less.")
        st.write("Compare storage with the same time of year: stocks usually rise ahead of winter and fall during the heating season. A larger stock can provide more cushion, but a build or surplus alone does not predict the next price move.")
        if not stocks.empty:
            recent = stocks.tail(156)
            fig = go.Figure()
            if {"five_year_min", "five_year_max"}.issubset(recent.columns):
                fig.add_trace(go.Scatter(x=recent.date, y=recent.five_year_max, line=dict(width=0), showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=recent.date, y=recent.five_year_min, line=dict(width=0), fill="tonexty", fillcolor="rgba(117,169,255,.12)", name="Previous five years: seasonal range"))
            if "five_year_avg" in recent:
                fig.add_trace(go.Scatter(x=recent.date, y=recent.five_year_avg, line=dict(color=MUTED, dash="dot"), name="Previous five years: seasonal average"))
            fig.add_trace(go.Scatter(x=recent.date, y=recent.storage_bcf, line=dict(color=BLUE, width=3), name="Gas in storage"))
            fig.update_yaxes(title="Gas in storage · billion cubic feet (Bcf)")
            st.caption("Blue is reported storage. When a seasonal comparison is available, blue above the dotted average means more gas stored than usual for that point in the year. The shaded band is the range of the previous five seasonal observations.")
            _chart(style(fig, 340), "context_gas_storage")
    else:
        st.info("The latest storage observation is unavailable.")
    if eia.get("storage_source_url"):
        st.markdown(f"[EIA working-gas storage history]({eia['storage_source_url']})")
    _source_details(eia, "EIA data and definitions", "The five-year benchmark is calculated by this dashboard from the nearest seasonal week in each of the five preceding calendar years, and can differ from EIA’s published average. Weekly stock differences can include reclassifications between categories of stored gas.")


def render_glossary():
    with st.expander("Quick guide to the words you’ll see"):
        st.markdown("""
| Term | In plain English |
| --- | --- |
| Forecast / model run | A model’s estimate of future weather. Each run is a new forecast made at a particular time. |
| Normal / usual | The historical seasonal benchmark. The weather comparisons here use 1991–2020, rather than yesterday or a comfortable indoor temperature. |
| Anomaly | Forecast or observed value minus its normal. A temperature anomaly of +5°F means 5°F warmer than usual. |
| Revision | What changed between forecasts for the **same future dates**. It is different from being above or below normal. |
| HDD / heating degree days | A cold-weather demand measure: how far a day’s average temperature is below 65°F. More HDD means greater heating need. |
| CDD / cooling degree days | A hot-weather demand measure: how far a day’s average temperature is above 65°F. More CDD means greater cooling need. |
| Population weighted | Regions with more people have more influence on the national average. |
| Power burn | Natural gas burned by power plants to make electricity, including electricity for air conditioning. |
| Bcf / Bcf per day | One billion cubic feet of gas / that amount per day. These are gas volumes, not dollar values. |
| Subseasonal outlook | A broad look a few weeks ahead. It describes temperature odds over a period, rather than exact daily weather. |
| Ensemble / spread | A group of related model forecasts / how much those forecasts disagree. |
| Stale | A source’s observation or forecast is older than this dashboard’s expected update window. Refreshing cannot make an old observation new. |
""")
