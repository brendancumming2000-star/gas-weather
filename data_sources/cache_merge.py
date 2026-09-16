"""Retain last-good CPC components without changing their source dates.

Only the bounded CPC component set is merged. Forecast members/initializations
and observation summaries are atomic bundles; dates and numbers never cross
bundles. This helper performs no I/O and does not mutate either input payload.
"""
from copy import deepcopy
from datetime import datetime, timezone
import re

_OBSERVATION_FIELDS = ("observed_at", "date", "value", "history", "percentile", "baseline", "source_url")
_FORECAST_FIELDS = ("forecast", "forecast_initialized_at", "forecast_mean_days8_15", "forecast_source_url", "forecast_methodology")
_OUTLOOK_NAMES = ("6–10 day", "8–14 day", "Weeks 3–4")


def _source_time(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _observations_available(nao):
    return bool(nao.get("history")) and nao.get("value") is not None and _source_time(nao.get("observed_at")) is not None


def _forecast_available(nao):
    return bool(nao.get("forecast")) and _source_time(nao.get("forecast_initialized_at")) is not None


def refresh_cpc_freshness(payload, now=None):
    """Recompute each CPC component's age from source dates, never pull time."""
    result = deepcopy(payload)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    # Remove only previously generated age messages, preserving fetch errors.
    warnings = [w for w in result.get("warnings", []) if not (
        str(w).startswith("Stale CPC ") or
        re.match(r"NAO observations are \d+ days old;", str(w)) or
        str(w).startswith("NAO ensemble initialization is stale:") or
        any(str(w).startswith(f"{name} outlook is stale:") for name in _OUTLOOK_NAMES)
    )]
    nao = result.get("nao") or {}
    dated = []
    if _observations_available(nao):
        dated.append(("NAO observations", nao["observed_at"], 4))
    if _forecast_available(nao):
        dated.append(("NAO ensemble initialization", nao["forecast_initialized_at"], 2))
    for outlook in result.get("outlooks", []):
        name = outlook.get("name", "outlook")
        if _source_time(outlook.get("observed_at")):
            dated.append((name + " outlook", outlook["observed_at"], 10 if name == "Weeks 3–4" else 3))
    for label, source_date, max_days in dated:
        age = (now.date() - _source_time(source_date).date()).days
        if age > max_days:
            warnings.append(f"Stale CPC {label}: source date {source_date} ({age} days old).")
    result["warnings"] = list(dict.fromkeys(warnings))
    # This aggregate describes the newest component, while per-product dates and
    # warnings identify older data. Never replace a retained date with now.
    if dated:
        result["observed_at"] = max((date for _, date, _ in dated), key=_source_time)
    return result


def merge_cached_subproducts(name, payload, previous_payload):
    """Return a fresh payload with missing CPC portions retained explicitly.

    Call with the prior snapshot's ``payload`` (not its database envelope).
    Non-CPC sources are returned unchanged by value. Retention is unlimited in
    age so useful history stays visible, but old dates always trigger warnings.
    """
    result = deepcopy(payload)
    if name == 'noaa_maps':
        previous = previous_payload or {}
        warnings = result.setdefault('warnings', [])
        # An archive issue can fill a failed request only for the same requested
        # day. A prior bundle must never become today's "yesterday" by relabeling.
        if result.get('requested_previous_date') and result.get('requested_previous_date') == previous.get('requested_previous_date'):
            maps = {p['name']: p for p in result.get('previous_outlooks', [])}
            for old in previous.get('previous_outlooks', []):
                if old.get('image_base64') and not maps.get(old['name'], {}).get('image_base64'):
                    maps[old['name']] = deepcopy(old)
                    maps[old['name']]['retained_from_cache'] = True
                    warnings.append(f"Retained saved {old['name']} map issued {old.get('observed_at')}; the archive request failed.")
            result['previous_outlooks'] = [maps[key] for key in _OUTLOOK_NAMES if key in maps]
        if (not result.get('seasonal', {}).get('image_base64')
                and result.get('requested_season')
                and result.get('requested_season') == previous.get('requested_season')
                and previous.get('seasonal', {}).get('image_base64')):
            result['seasonal'] = deepcopy(previous['seasonal'])
            result['seasonal']['retained_from_cache'] = True
            warnings.append(f"Retained seasonal map issued {previous['seasonal'].get('observed_at')}; a newer issue could not be checked.")
        return result
    if name != "cpc":
        return result
    previous = previous_payload or {}
    warnings = result.setdefault("warnings", [])
    nao = result.setdefault("nao", {}) or {}
    result["nao"] = nao
    old_nao = previous.get("nao") or {}
    if not _observations_available(nao) and _observations_available(old_nao):
        for key in _OBSERVATION_FIELDS:
            nao.pop(key, None)
            if key in old_nao:
                nao[key] = deepcopy(old_nao[key])
        warnings.append(f"Retained cached CPC NAO observations: source date {old_nao['observed_at']}; current observation pull unavailable.")
    if not _forecast_available(nao) and _forecast_available(old_nao):
        for key in _FORECAST_FIELDS:
            nao.pop(key, None)
            if key in old_nao:
                nao[key] = deepcopy(old_nao[key])
        warnings.append(f"Retained cached CPC NAO ensemble: initialized {old_nao['forecast_initialized_at']}; current forecast pull unavailable.")
    current_outlooks = {item["name"]: item for item in result.get("outlooks", []) if item.get("name") in _OUTLOOK_NAMES and _source_time(item.get("observed_at"))}
    old_outlooks = {item["name"]: item for item in previous.get("outlooks", []) if item.get("name") in _OUTLOOK_NAMES and _source_time(item.get("observed_at"))}
    for outlook_name in _OUTLOOK_NAMES:
        if outlook_name not in current_outlooks and outlook_name in old_outlooks:
            retained = deepcopy(old_outlooks[outlook_name])
            current_outlooks[outlook_name] = retained
            warnings.append(f"Retained cached CPC {outlook_name} outlook: issued {retained['observed_at']}; current product pull unavailable.")
        elif outlook_name in current_outlooks and outlook_name in old_outlooks:
            current, old = current_outlooks[outlook_name], old_outlooks[outlook_name]
            if (not current.get("image_base64") and old.get("image_base64")
                    and current.get("observed_at") == old.get("observed_at")):
                # A cached map may fill an image outage only for the exact same
                # issue. Never graft yesterday's map onto today's outlook.
                for key in ("image_base64", "image_mime_type", "image_snapshot_fetched_at"):
                    if key in old:
                        current[key] = deepcopy(old[key])
                warnings.append(f"Retained cached CPC {outlook_name} map image for the same issue date {old['observed_at']}; current image pull unavailable.")
    result["outlooks"] = [current_outlooks[key] for key in _OUTLOOK_NAMES if key in current_outlooks]
    return refresh_cpc_freshness(result)
