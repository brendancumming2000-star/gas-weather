"""NOAA CPC NAO observations/GEFS ensembles and operational temperature outlooks."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import base64
from html import unescape
from io import StringIO
import re

import numpy as np
import pandas as pd

from data_sources.common import get_bytes, get_text
from data_sources.cache_merge import refresh_cpc_freshness

NAO_OBS_URL = "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.cdas.z500.19500101_current.csv"
NAO_FORECAST_URL = "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.gefs.z500.120days.csv"
NAO_PAGE = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/nao_index.html"
CPC_BASE = "https://www.cpc.ncep.noaa.gov/products/predictions/"
DISCUSSION_URL = CPC_BASE + "610day/fxus06.html"
OUTLOOKS = [
    ("6–10 day", "610day/", "610day/610temp.new.gif"),
    ("8–14 day", "814day/", "814day/814temp.new.gif"),
    ("Weeks 3–4", "WK34/", "WK34/gifs/WK34temp.gif"),
]
MAX_OUTLOOK_IMAGE_BYTES = 5 * 1024 * 1024
_REGION_STATES = {
    "Northeast": ["NEW YORK", "VERMONT", "NEW HAMP", "MAINE", "MASS", "CONN", "RHODE IS"],
    "Midwest": ["MINNESOTA", "IOWA", "MISSOURI", "N DAKOTA", "S DAKOTA", "NEBRASKA", "KANSAS"],
    "Great Lakes": ["WISCONSIN", "ILLINOIS", "MICHIGAN", "INDIANA", "OHIO"],
}


def _plain(html: str) -> str:
    """Keep actual source paragraph/line breaks but remove navigation markup."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.I | re.S)
    html = re.sub(r"<(?:br\b[^>]*|/?p\b[^>]*)>", "\n", html, flags=re.I)
    return unescape(re.sub(r"<[^>]+>", "", html)).replace("\xa0", " ")


def _percentile(values, current):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(100 * ((values < current).sum() + 0.5 * (values == current).sum()) / len(values)) if len(values) else None


def encode_outlook_image(data: bytes) -> dict:
    """Snapshot an actual raster response; reject HTML errors/oversized bodies."""
    if not 24 <= len(data) <= MAX_OUTLOOK_IMAGE_BYTES:
        raise ValueError("CPC image body is empty/truncated or exceeds the 5 MiB limit")
    if data.startswith((b"GIF87a", b"GIF89a")):
        mime_type = "image/gif"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    else:
        raise ValueError("CPC map response does not have a GIF or PNG signature")
    return {"image_base64": base64.b64encode(data).decode("ascii"), "image_mime_type": mime_type}


def parse_nao_observations(text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text))
    expected = {"year", "month", "day", "nao_index_cdas"}
    if not expected.issubset(frame.columns):
        raise ValueError("CPC NAO observation schema changed")
    frame["date"] = pd.to_datetime(frame[["year", "month", "day"]], errors="coerce")
    frame["value"] = pd.to_numeric(frame["nao_index_cdas"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"])
    frame = frame[np.isfinite(frame.value) & frame.value.between(-20, 20)]
    if frame.empty:
        raise ValueError("CPC NAO contains no valid observations")
    return frame[["date", "value"]].drop_duplicates("date").sort_values("date")


def parse_nao_forecasts(text: str) -> dict:
    frame = pd.read_csv(StringIO(text))
    if not {"lead", "member", "time", "nao_index", "valid_time"}.issubset(frame.columns):
        raise ValueError("CPC GEFS NAO schema changed")
    for field in ["time", "valid_time"]:
        frame[field] = pd.to_datetime(frame[field], errors="coerce")
    frame["nao_index"] = pd.to_numeric(frame.nao_index, errors="coerce")
    frame["lead"] = pd.to_numeric(frame.lead, errors="coerce")
    frame = frame.dropna(subset=["time", "valid_time", "nao_index", "lead", "member"])
    frame = frame[frame.nao_index.between(-20, 20) & frame.lead.between(0, 15)]
    frame = frame[(frame.valid_time - frame.time).dt.days == frame.lead]
    frame = frame.drop_duplicates(["time", "valid_time", "member"])
    if frame.empty:
        raise ValueError("CPC GEFS NAO contains no valid dated forecasts")
    initialized = frame.time.max()
    current = frame[frame.time == initialized]
    previous = frame[frame.time == initialized - pd.Timedelta(days=1)]
    prior_means = previous.groupby("valid_time").nao_index.mean()
    rows = []
    for valid, group in current.groupby("valid_time"):
        values = group.nao_index
        mean = float(values.mean())
        prior = float(prior_means.loc[valid]) if valid in prior_means.index else None
        rows.append({"date": valid.date().isoformat(), "lead_days": int(group.lead.iloc[0]),
                     "mean": mean, "p10": float(values.quantile(.1)), "p90": float(values.quantile(.9)),
                     "member_count": int(group.member.nunique()), "prior_mean": prior,
                     "change": mean - prior if prior is not None else None})
    future = current[current.lead.between(8, 15)]
    return {"forecast": rows, "forecast_initialized_at": initialized.date().isoformat(),
            "forecast_mean_days8_15": float(future.groupby("valid_time").nao_index.mean().mean()) if not future.empty else None,
            "forecast_source_url": NAO_FORECAST_URL,
            "forecast_methodology": "CPC GEFS members; daily ensemble mean and 10th–90th member percentiles, not calibrated confidence intervals. Previous initialization is exactly one calendar day earlier; revisions match valid dates. Index units are standardized and dimensionless."}


def fetch_nao() -> dict:
    result = {"observed_at": None, "date": None, "value": None, "history": [],
              "percentile": None, "source_url": NAO_OBS_URL, "forecast": [], "warnings": []}
    # The two files are independently useful. An observation endpoint outage
    # must not prevent a fresh ensemble forecast from being fetched and cached.
    try:
        observations = parse_nao_observations(get_text(NAO_OBS_URL))
        latest = observations.iloc[-1]
        baseline = observations[observations.date.dt.year.between(1991, 2020) & (observations.date.dt.month == latest.date.month)]
        recent = observations.tail(1096).copy()
        recent["date"] = recent.date.dt.strftime("%Y-%m-%d")
        result.update({"observed_at": latest.date.date().isoformat(), "date": latest.date.date().isoformat(),
                       "value": float(latest.value), "history": recent.to_dict("records"),
                       "percentile": _percentile(baseline.value, latest.value),
                       "baseline": "1991–2020 observations from the same calendar month; midpoint empirical percentile"})
    except Exception as exc:
        result["warnings"].append(f"NAO observations unavailable: {exc}")
    try:
        result.update(parse_nao_forecasts(get_text(NAO_FORECAST_URL)))
    except Exception as exc:
        result["warnings"].append(f"Numeric NAO ensemble unavailable: {exc}")
        result["forecast_page_url"] = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/new.nao_index_ensm.html"
    if not result["history"] and not result["forecast"]:
        raise RuntimeError("; ".join(result["warnings"]))
    return result


def parse_state_categories(discussion: str, period: str) -> list[dict]:
    heading = "6-10 DAY OUTLOOK TABLE" if period == "6–10 day" else "8-14 DAY OUTLOOK TABLE"
    text = _plain(discussion)
    if heading not in text:
        return []
    section = text.split(heading, 1)[1].split("LEGEND", 1)[0].split("8-14 DAY OUTLOOK TABLE", 1)[0]
    states = []
    for line in section.splitlines():
        for state, temperature, _precipitation in re.findall(r"([A-Z][A-Z ]*?)\s+([ABN])\s+([ABN])(?:\s{2,}|$)", line):
            states.append({"state": state.strip(), "temperature_category": {"A": "Above normal", "B": "Below normal", "N": "Near normal"}[temperature]})
    return states


def _regional_summaries(categories):
    by_state = {row["state"]: row["temperature_category"] for row in categories}
    result = []
    for region, states in _REGION_STATES.items():
        values = [by_state[s] for s in states if s in by_state]
        counts = {label: values.count(label) for label in ["Above normal", "Near normal", "Below normal"]}
        summary = "; ".join(f"{n}/{len(values)} state categories {label.lower()}" for label, n in counts.items() if n)
        result.append({"region": region, "summary": summary or "State categories unavailable; inspect official map."})
    return result


def category_definition_from_page(page: str) -> str:
    """Quote the retrieved product's temperature legend, without a frozen schema.

    CPC products can change categories while older linked FAQs remain online.
    Only an actual temperature-map legend sentence establishes the definition.
    """
    plain = re.sub(r"\s+", " ", _plain(page)).strip()
    match = re.search(r"The shading on the temperature map\b[^.]*\.", plain, re.I)
    if match and re.search(r"categor", match.group(0), re.I):
        return match.group(0).strip()
    return "See official legend"


def parse_outlook(page: str, name: str, source_url: str, image_url: str, discussion: str = "") -> dict:
    plain = _plain(page)
    updated = re.search(r"Updated:\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", plain)
    if not updated:
        raise ValueError(f"{name} issue date missing from CPC page")
    issued = datetime.strptime(updated.group(1), "%d %b %Y").date().isoformat()
    valid = re.search(r"Valid:\s*([^\n]+)", plain)
    valid_period = re.sub(r"\s+", " ", valid.group(1)).strip() if valid else "See official map"
    if name == "Weeks 3–4":
        start = plain.find("Prognostic Discussion for Week 3-4")
        end = plain.find("An ASCII", start)
        written = plain[start:end].strip() if start >= 0 else ""
        # Source sentences only. Do not infer numerical probabilities from prose or map colors.
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", written))
        regional = []
        terms = {"Northeast": r"Northeast|New England", "Midwest": r"Midwest|Mississippi|Plains", "Great Lakes": r"Great Lakes|Ohio Valley"}
        for region, pattern in terms.items():
            matching = [s for s in sentences if re.search(pattern, s, re.I) and re.search(r"temperatur|warm|cold|cool", s, re.I)]
            if matching:
                summary = " ".join(matching[:2])
            else:
                broad = [s for s in sentences if re.search(r"\bcentral(?: and northeastern)? regions of CONUS\b", s, re.I)
                         and re.search(r"temperatur|warm|cold|cool", s, re.I)]
                summary = ("Broader CONUS context; no separate regional forecast: " + broad[0]) if broad else "No separate regional temperature statement parsed; inspect the probability map."
            regional.append({"region": region, "summary": summary})
        categories = []
    else:
        pre = re.search(r"<pre[^>]*>(.*?)</pre>", discussion, re.I | re.S)
        written = _plain(pre.group(1)) if pre else ""
        begin = "6-10 DAY OUTLOOK FOR" if name == "6–10 day" else "8-14 DAY OUTLOOK FOR"
        start = written.find(begin)
        written = written[start:] if start >= 0 else written
        terminator = "8-14 DAY OUTLOOK FOR" if name == "6–10 day" else "FORECASTER:"
        written = written.split(terminator, 1)[0].strip()
        categories = parse_state_categories(discussion, name)
        regional = _regional_summaries(categories)
    return {"name": name, "observed_at": issued, "valid_period": valid_period,
            "source_url": source_url, "image_url": image_url,
            "product_type": "Probabilistic CPC temperature outlook",
            "category_definition": category_definition_from_page(page),
            "discussion": written, "discussion_url": source_url if name == "Weeks 3–4" else DISCUSSION_URL,
            "regional_summary": regional, "state_categories": categories,
            "methodology": "CPC probabilities describe period-mean temperature categories, not daily temperatures, HDDs, or a deterministic forecast. State counts are unweighted categorical summaries, not region-wide probabilities. Category definitions come from the retrieved product's own temperature legend when available; otherwise consult its official legend. Europe is outside these U.S. products."}


def fetch_cpc() -> dict:
    result = {"source_url": NAO_PAGE, "nao": {}, "outlooks": [], "warnings": [],
              "methodology": "Observed CPC CDAS NAO and numerical GEFS NAO ensemble; official CPC probabilistic temperature products provide subseasonal context. CPC Week 3–4 is the operational substitute for a separate raw SubX ingestion."}
    jobs = {"nao": fetch_nao, "discussion": lambda: get_text(DISCUSSION_URL)}
    jobs.update({name: (lambda path=path: get_text(CPC_BASE + path)) for name, path, _ in OUTLOOKS})
    fetched = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fn): key for key, fn in jobs.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                fetched[key] = future.result()
            except Exception as exc:
                result["warnings"].append(f"CPC {key} unavailable: {exc}")
    if "nao" in fetched:
        result["nao"] = fetched["nao"]
        result["warnings"].extend(fetched["nao"]["warnings"])
    for name, path, image in OUTLOOKS:
        if name not in fetched:
            continue
        try:
            result["outlooks"].append(parse_outlook(fetched[name], name, CPC_BASE + path, CPC_BASE + image, fetched.get("discussion", "")))
        except Exception as exc:
            result["warnings"].append(f"CPC {name} could not be parsed: {exc}")
    # Operational image URLs are mutable. Store the bytes alongside this pull's
    # issue-date metadata so historical/cache views cannot silently show a newer
    # map. The original URL remains a source link, never a display fallback.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(get_bytes, outlook["image_url"]): outlook for outlook in result["outlooks"]}
        for future in as_completed(futures):
            outlook = futures[future]
            try:
                outlook.update(encode_outlook_image(future.result()))
                outlook["image_snapshot_fetched_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                result["warnings"].append(f"CPC {outlook['name']} map snapshot unavailable: {exc}; use the official source link.")
    dates = [o["observed_at"] for o in result["outlooks"]]
    dates.extend(result["nao"][k] for k in ["observed_at", "forecast_initialized_at"] if result["nao"].get(k))
    if not dates:
        raise RuntimeError("No usable CPC observations or outlooks; " + "; ".join(result["warnings"]))
    result["observed_at"] = max(dates)
    return refresh_cpc_freshness(result)
