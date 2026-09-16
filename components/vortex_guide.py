"""Short homepage guide; fresh model clues are never cold-outbreak probabilities."""
from __future__ import annotations

import math

import streamlit as st

from models.signals import vortex_risk
from storage.database import parse_time, utcnow


VORTEX_SOURCE = "https://www.climate.gov/news-features/understanding-climate/understanding-arctic-polar-vortex"
WARMING_SOURCE = "https://content-drupal.climate.gov/news-features/blogs/enso/el-ni%C3%B1o-and-stratospheric-polar-vortex"
NAO_SOURCE = "https://www.cpc.ncep.noaa.gov/data/teledoc/nao.shtml"


def _issued(value):
    try:
        return parse_time(value).strftime("%b %d, %Y at %H:%M UTC")
    except (TypeError, ValueError):
        return "date unavailable"


def _fresh(value, now, hours):
    try:
        age = (now - parse_time(value)).total_seconds() / 3600
        return 0 <= age <= hours
    except (TypeError, ValueError):
        return False


def vortex_watch(gfs, now=None):
    """Return a plain-language watch state; reject stale data and nonwinter signals."""
    now = parse_time(now) if now is not None else utcnow()
    gfs = gfs or {}
    if now.month not in (11, 12, 1, 2, 3):
        return "Winter watch is not active", f"It is {now.strftime('%B')}. This dashboard checks winter wind changes in November–March; off-season changes do not predict a winter cold outbreak."
    issued = gfs.get("model_run") or gfs.get("observed_at")
    if not _fresh(issued, now, 18):
        return "Current winter clue unavailable", "The saved high-altitude forecast is missing, undated, or more than 18 hours old."
    pv = gfs.get("polar_vortex") or {}
    try:
        label, _ = vortex_risk(pv)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        label = "Unavailable"
    if label == "Moderate":
        try:
            initial_wind = float(pv["rows"][0]["u10_ms"])
        except (TypeError, ValueError, KeyError, IndexError):
            initial_wind = math.nan
        if initial_wind < 0:
            return "Unusual winter winds already present", "The forecast starts with winds blowing east to west. This does not establish a new disruption or where cold air will go."
        if initial_wind > 0 and pv.get("winter_westerly_to_easterly_transition", True):
            return "A winter wind change to watch", "One forecast shows high-altitude winds reversing direction. That is a clue to watch, not confirmation of a U.S. cold outbreak."
        return "Unusual winter winds in the forecast", "Some sampled winds blow east to west; the data do not establish a new reversal or where cold air will go."
    if label == "Low":
        return "No winter wind reversal forecast", "The complete sampled forecast keeps winds west to east. Cold spells can still develop through other weather patterns."
    return "Current winter clue unavailable", "There is not enough valid winter wind data to assess this clue."


def _nao_note(cpc, now):
    nao = (cpc or {}).get("nao") or {}
    value = nao.get("forecast_mean_days8_15")
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or not _fresh(nao.get("forecast_initialized_at"), now, 48):
        return "A current Atlantic-pattern forecast is unavailable."
    direction = "negative" if value < 0 else "positive" if value > 0 else "near zero"
    return (f"The Atlantic-pattern forecast for days 8–15 averages {direction} ({value:+.2f}); "
            f"issued {_issued(nao.get('forecast_initialized_at'))}. "
            "This describes a pressure pattern, not a temperature or a chance of cold.")


def render_vortex_guide(gfs, cpc):
    gfs = gfs or {}
    st.subheader("Could Arctic cold reach us?")
    st.markdown(
        "The **polar vortex** is a ring of strong winds high above the Arctic that normally forms each winter. "
        "We watch whether it gets disturbed—and whether colder air can then reach populated areas. "
        f"[NOAA explainer]({VORTEX_SOURCE})"
    )
    first, second, third = st.columns(3, gap="large")
    with first:
        st.markdown("**1. A push from below**")
        st.markdown("Large bends in weather patterns can send energy upward and disturb those high winds.")
    with second:
        st.markdown("**2. Warming high above the Arctic**")
        st.markdown(
            "Rapid warming can accompany weakening or reversing winds. **Sudden stratospheric warming** "
            f"means warming high overhead. [NOAA]({WARMING_SOURCE})"
        )
    with third:
        st.markdown("**3. A route for cold air**")
        st.markdown(
            "Persistent high pressure—**blocking**—can redirect weather. Its location and the lower jet stream "
            f"help determine who gets cold. [NOAA]({NAO_SOURCE})"
        )
    st.caption("These clues do not guarantee U.S. cold. Gas demand rises if the cold actually reaches places using heating.")
    title, detail = vortex_watch(gfs)
    st.info(f"**{title}.** {detail}")
    with st.expander("More about this winter watch"):
        st.write("The first two clues concern disruption of the high-altitude vortex; the third concerns where cold air might travel. The lower jet stream steers everyday weather, in a different layer of the atmosphere.")
        st.write("The dashboard samples one NOAA weather-model forecast of high-altitude winds. It does not measure upward wave energy or establish a warming event from the wind alone. A change overhead may affect surface weather weeks later, or have little effect in your region.")
        st.caption(f"Saved high-altitude forecast issued {_issued(gfs.get('model_run') or gfs.get('observed_at'))}.")
        st.write(_nao_note(cpc, utcnow()))
        st.markdown(f"**NAO** means North Atlantic Oscillation. A negative reading describes a pressure pattern that can favor blocking near Greenland; it does not prove that the vortex is breaking down. [CPC explanation]({NAO_SOURCE})")
        st.write("Snow cover and sea ice provide background context, but neither alone establishes that a vortex disruption or a U.S. cold spell is coming. See Cold-weather clues for the saved data and charts.")
        st.markdown(f"[NOAA: how the vortex and surface weather connect]({VORTEX_SOURCE})")
