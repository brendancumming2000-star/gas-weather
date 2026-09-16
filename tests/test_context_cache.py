"""CPC failures must preserve coherent, separately dated component bundles."""
from copy import deepcopy
from datetime import datetime, timezone

from data_sources import cpc
from data_sources.cache_merge import merge_cached_subproducts, refresh_cpc_freshness


def previous_payload():
    return {"observed_at": "2020-01-03", "warnings": ["Old failed pull"],
            "nao": {"observed_at": "2020-01-02", "date": "2020-01-02", "value": 0,
                    "history": [{"date": "2020-01-02", "value": 0}], "percentile": 50,
                    "baseline": "old baseline", "forecast": [{"date": "2020-01-04", "mean": -1}],
                    "forecast_initialized_at": "2020-01-03", "forecast_mean_days8_15": -1,
                    "forecast_source_url": "https://example.invalid/forecast"},
            "outlooks": [{"name": name, "observed_at": "2020-01-01", "discussion": "old discussion"}
                         for name in ("6–10 day", "8–14 day", "Weeks 3–4")]}


def test_missing_observations_keep_fresh_forecast_and_input_payloads_unchanged():
    previous = previous_payload()
    current = {"warnings": ["NAO observations unavailable: request failed"], "outlooks": [],
               "nao": {"history": [], "observed_at": None, "value": None,
                       "forecast": [{"date": "2020-01-08", "mean": 2}],
                       "forecast_initialized_at": "2020-01-07", "forecast_mean_days8_15": 2}}
    originals = deepcopy((previous, current))
    result = merge_cached_subproducts("cpc", current, previous)
    assert result["nao"]["value"] == 0  # zero is a valid observation
    assert result["nao"]["observed_at"] == "2020-01-02"
    assert result["nao"]["forecast_initialized_at"] == "2020-01-07"
    assert result["nao"]["forecast_mean_days8_15"] == 2
    assert result["observed_at"] == "2020-01-07"
    assert any("Retained cached CPC NAO observations" in w for w in result["warnings"])
    assert any("Stale CPC NAO observations" in w and "2020-01-02" in w for w in result["warnings"])
    assert not any("Retained cached CPC NAO ensemble" in w for w in result["warnings"])
    assert (previous, current) == originals


def test_missing_forecast_is_retained_atomically_and_outlooks_merge_by_name():
    previous = previous_payload()
    current = {"warnings": ["Numeric NAO ensemble unavailable"],
               "nao": {"observed_at": "2020-01-08", "date": "2020-01-08", "value": 3,
                       "history": [{"date": "2020-01-08", "value": 3}], "forecast": [],
                       "forecast_initialized_at": "2099-01-01", "forecast_mean_days8_15": 999},
               "outlooks": [{"name": "8–14 day", "observed_at": "2020-01-09", "discussion": "new discussion"}]}
    result = merge_cached_subproducts("cpc", current, previous)
    assert result["nao"]["observed_at"] == "2020-01-08"
    assert result["nao"]["forecast_initialized_at"] == "2020-01-03"
    assert result["nao"]["forecast_mean_days8_15"] == -1
    assert len(result["outlooks"]) == 3
    assert result["outlooks"][1]["discussion"] == "new discussion"
    assert result["outlooks"][0]["observed_at"] == "2020-01-01"
    assert result["observed_at"] == "2020-01-09"
    assert "Old failed pull" not in result["warnings"]
    assert any("Retained cached CPC NAO ensemble" in w for w in result["warnings"])
    assert any("Stale CPC 6–10 day outlook" in w for w in result["warnings"])
    again = merge_cached_subproducts("cpc", current, result)
    assert again == result


def test_freshness_is_recomputed_from_each_actual_date_not_new_composite_date():
    payload = previous_payload()
    payload["warnings"] = ["Stale CPC NAO observations: bogus age.", "Connection failure"]
    result = refresh_cpc_freshness(payload, datetime(2020, 1, 10, tzinfo=timezone.utc))
    assert any("NAO observations: source date 2020-01-02 (8 days old)" in w for w in result["warnings"])
    assert any("NAO ensemble initialization: source date 2020-01-03 (7 days old)" in w for w in result["warnings"])
    assert any("6–10 day outlook: source date 2020-01-01 (9 days old)" in w for w in result["warnings"])
    assert not any("Stale CPC Weeks 3–4" in w for w in result["warnings"])
    assert "Connection failure" in result["warnings"]
    assert not any("bogus" in w for w in result["warnings"])
    assert result["observed_at"] == "2020-01-03"


def test_recovery_does_not_inherit_prior_failure_warnings_and_other_sources_pass_through():
    complete = previous_payload()
    complete["warnings"] = []
    previous = deepcopy(complete)
    previous["warnings"] = ["Retained cached CPC NAO ensemble: old outage"]
    result = merge_cached_subproducts("cpc", complete, previous)
    assert not any(w.startswith("Retained") for w in result["warnings"])
    assert merge_cached_subproducts("snow", {"observed_at": "2020-01-02"}, {"extra": 3}) == {"observed_at": "2020-01-02"}


def test_nao_forecast_is_attempted_even_when_observation_endpoint_fails(monkeypatch):
    attempts = []

    def get_text(url):
        attempts.append(url)
        if url == cpc.NAO_OBS_URL:
            raise ConnectionError("temporary observation outage")
        return "lead,member,time,nao_index,valid_time\n8,0,2026-01-01,-1,2026-01-09\n"

    monkeypatch.setattr(cpc, "get_text", get_text)
    result = cpc.fetch_nao()
    assert attempts == [cpc.NAO_OBS_URL, cpc.NAO_FORECAST_URL]
    assert result["history"] == []
    assert result["observed_at"] is None
    assert result["forecast_mean_days8_15"] == -1
    assert any("observations unavailable" in warning for warning in result["warnings"])


def test_outlook_image_retention_requires_matching_issue_date():
    previous = previous_payload()
    for item in previous["outlooks"]:
        item.update({"image_base64": "stored-image", "image_mime_type": "image/gif", "image_snapshot_fetched_at": "2020-01-01T19:00:00+00:00"})
    current = {"warnings": [], "nao": {}, "outlooks": [
        {"name": "6–10 day", "observed_at": "2020-01-01"},
        {"name": "8–14 day", "observed_at": "2020-01-02"},
    ]}
    result = merge_cached_subproducts("cpc", current, previous)
    assert result["outlooks"][0]["image_base64"] == "stored-image"
    assert result["outlooks"][0]["image_snapshot_fetched_at"] == "2020-01-01T19:00:00+00:00"
    assert "image_base64" not in result["outlooks"][1]
    assert result["outlooks"][2]["image_base64"] == "stored-image"
    assert any("map image for the same issue date" in warning for warning in result["warnings"])
