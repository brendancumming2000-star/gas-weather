"""Dated NOAA CPC maps for yesterday, plus the latest Nov–Jan seasonal outlook.

Only archived daily/weekly bytes are used for historical products. The operational
seasonal map is snapshotted after resolving its season and verifying its issue.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from PIL import Image

from data_sources.common import get_bytes, get_text
from data_sources.cpc import _plain, encode_outlook_image

CPC = "https://www.cpc.ncep.noaa.gov"
SHORT_ARCHIVE = CPC + "/products/archives/short_range/"
WEEK_ARCHIVE = CPC + "/products/predictions/WK34/archives/"
SEASON_PAGE = CPC + "/products/predictions/long_range/seasonal.php"
SEASON_DISCUSSION = CPC + "/products/predictions/long_range/fxus05.html"
PUBLICATION_ZONE = ZoneInfo("America/New_York")
_MONTHS = {name: i for i, name in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def requested_context(now: datetime | None = None) -> dict:
    """Calendar boundary follows CPC's Eastern publication day, including DST.

    A naive test clock is interpreted as UTC. In January retain the current
    Nov–Jan season; in February advance to the next November.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_day = current.astimezone(PUBLICATION_ZONE).date()
    year = local_day.year - (local_day.month == 1)
    return {"requested_previous_date": (local_day - timedelta(days=1)).isoformat(),
            "requested_season": f"NDJ {year}–{str(year + 1)[-2:]}",
            "season_start": f"{year}-11-01", "season_end": f"{year + 1}-01-31",
            "publication_timezone": "America/New_York"}


def _date(month: str, day: str, year: str | int) -> date:
    return date(int(year), _MONTHS[month[:3].upper()], int(day))


def parse_issue(text: str) -> date:
    """Read the forecaster's dateline, not dates mentioned in discussion prose."""
    header = _plain(text)
    start = header.find("Prognostic Discussion")
    header = header[start:start + 550] if start >= 0 else header[:550]
    match = re.search(r"\b(?:EST|EDT)\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
                      r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})\b", header, re.I)
    if not match:
        raise ValueError("NOAA issue dateline is missing")
    return _date(*match.groups())


def _period(start: date, end: date) -> dict:
    if end < start:
        raise ValueError("NOAA valid period ends before it starts")
    return {"valid_start": start.isoformat(), "valid_end": end.isoformat(),
            "valid_period": f"{start.strftime('%b')} {start.day}, {start.year} – "
                            f"{end.strftime('%b')} {end.day}, {end.year}"}


def parse_short_metadata(text: str, issue: date, name: str) -> dict:
    actual = parse_issue(text)
    if actual != issue:
        raise ValueError(f"Archive dateline {actual} does not match requested issue {issue}")
    short, start_lead, end_lead = {"6–10 day": ("6-10", 6, 10), "8–14 day": ("8-14", 8, 14)}[name]
    match = re.search(rf"{short}\s+DAY\s+OUTLOOK\s+FOR\s+([A-Z]+)\s+(\d{{1,2}})"
                      r"\s*(\d{4})?\s*-\s*(?:([A-Z]+)\s+)?(\d{1,2})\s+(\d{4})", text, re.I)
    if not match:
        raise ValueError(f"{name} valid period missing from archived discussion")
    sm, sd, sy, em, ed, ey = match.groups()
    end = _date(em or sm, ed, ey)
    start_year = int(sy) if sy else int(ey) - (_MONTHS[sm[:3].upper()] > end.month)
    start = _date(sm, sd, start_year)
    if (start - issue).days != start_lead or (end - issue).days != end_lead:
        raise ValueError(f"{name} archive valid dates do not match its issue date")
    return {"observed_at": actual.isoformat(), "timestamp_precision": "date", **_period(start, end)}


def parse_week_metadata(text: str, issue: date) -> dict:
    actual = parse_issue(text)
    if actual != issue:
        raise ValueError(f"Weekly archive dateline {actual} does not match selected Friday {issue}")
    match = re.search(r"Week\s+3-4\s+Forecast\s+Discussion\s+Valid\s+"
                      r"(?:\w{3}\s+)?([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})\s*-\s*"
                      r"(?:\w{3}\s+)?([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})", _plain(text), re.I)
    if not match:
        raise ValueError("Weekly valid period missing from archived discussion")
    start, end = _date(*match.groups()[:3]), _date(*match.groups()[3:])
    if (start - issue).days != 15 or (end - start).days != 13:
        raise ValueError("Weekly archive valid dates do not match its issue date")
    return {"observed_at": actual.isoformat(), "timestamp_precision": "date", **_period(start, end)}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.images = [], []
        self.href, self.parts = None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.href, self.parts = attrs.get("href"), []
        if tag == "img" and attrs.get("src"):
            self.images.append(attrs["src"])

    def handle_data(self, data):
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.parts)))
            self.href = None


def _cpc_url(value: str, base: str = SEASON_PAGE) -> str:
    resolved = urljoin(base, value)
    parsed = urlparse(resolved)
    if parsed.scheme != "https" or parsed.hostname != "www.cpc.ncep.noaa.gov":
        raise ValueError("Map metadata linked outside official NOAA CPC HTTPS")
    return resolved


def select_season_link(page: str, season_year: int) -> str:
    links = _Links()
    links.feed(page)
    for href, label in links.links:
        label = re.sub(r"\s+", " ", label).strip()
        if re.fullmatch(rf"NDJ\s+{season_year}\s*[-–]\s*(?:{season_year + 1}|{str(season_year + 1)[-2:]})", label):
            return _cpc_url(href)
    raise ValueError(f"Latest seasonal product does not list NDJ {season_year}–{str(season_year + 1)[-2:]}")


def parse_season_image(page: str, season_year: int, page_url: str) -> str:
    # The selected heading must match. Finding NDJ in the navigation is insufficient.
    plain = re.sub(r"\s+", " ", _plain(page))
    expected = rf"OFFICIAL Forecasts\s+Nov-Dec-Jan\s+{season_year}\s*[-–]\s*(?:{season_year + 1}|{str(season_year + 1)[-2:]})\b"
    if not re.search(expected, plain, re.I):
        raise ValueError("Selected seasonal page is not the requested November–January period")
    links = _Links()
    links.feed(page)
    candidates = [src for src in links.images if re.search(r"/lead\d{2}/off\d{2}_temp\.gif$", src)]
    if len(set(candidates)) != 1:
        raise ValueError("Selected seasonal temperature image is missing or ambiguous")
    return _cpc_url(candidates[0], page_url)


def _snapshot(url: str) -> dict:
    data = get_bytes(url)
    encoded = encode_outlook_image(data)
    # Reject valid signatures with truncated/corrupt image bodies, too.
    with Image.open(BytesIO(data)) as image:
        image.verify()
    return {**encoded, "image_mime": encoded["image_mime_type"],
            "image_snapshot_fetched_at": datetime.now(timezone.utc).isoformat()}


def _short(issue: date, name: str, discussion: str) -> dict:
    folder = SHORT_ARCHIVE + issue.strftime("%Y/%m/%d/")
    code = "610" if name == "6–10 day" else "814"
    url = folder + f"{code}temp.{issue:%Y%m%d}.fcst.gif"
    return {"name": name, **parse_short_metadata(discussion, issue, name),
            "source_url": folder + f"PMDMRD.{issue:%Y%m%d}.txt", "image_url": url,
            "archive_url": SHORT_ARCHIVE + "srarc.ind.php", "is_dated_archive": True,
            "selection": "Issued on the previous Eastern calendar day", **_snapshot(url)}


def _weekly(previous: date) -> dict:
    expected = previous - timedelta(days=(previous.weekday() - 4) % 7)
    failures = []
    # Holidays/archive delays can leave the scheduled Friday absent. Look back
    # at most two extra weekly releases and retain the older issue's real date.
    for weeks_back in range(3):
        issue = expected - timedelta(weeks=weeks_back)
        folder = WEEK_ARCHIVE + issue.strftime("%Y/%m/%d/")
        source_url, image_url = folder + "week34fcst.txt", folder + "WK34temp.gif"
        try:
            result = {"name": "Weeks 3–4", **parse_week_metadata(get_text(source_url), issue),
                      "source_url": source_url, "image_url": image_url, "archive_url": WEEK_ARCHIVE,
                      "is_dated_archive": True, "expected_issue_date": expected.isoformat(),
                      "is_expected_weekly_issue": weeks_back == 0,
                      "selection": "Latest retrievable Friday archive as of the previous Eastern calendar day",
                      "publication_frequency": "Weekly, normally Friday", **_snapshot(image_url)}
            if failures:
                result["selection_warning"] = (
                    f"The scheduled Weeks 3–4 issue for {expected} could not be retrieved; "
                    f"showing the older {issue} issue. A newer map may exist at NOAA.")
            return result
        except Exception as exc:
            failures.append(f"{issue}: {exc}")
    raise ValueError("No usable weekly archive in three scheduled releases: " + "; ".join(failures))


def _seasonal(context: dict, now: datetime) -> dict:
    year = date.fromisoformat(context["season_start"]).year
    page_url = select_season_link(get_text(SEASON_PAGE), year)
    page = get_text(page_url)
    issue = parse_issue(get_text(SEASON_DISCUSSION))
    # Publication time is explicitly 08:30 Eastern in the operational product.
    issue_time = datetime(issue.year, issue.month, issue.day, 8, 30, tzinfo=PUBLICATION_ZONE)
    if issue_time > now:
        raise ValueError("Seasonal issue is later than the requested clock")
    image_url = parse_season_image(page, year, page_url)
    snapshot = _snapshot(image_url)
    # Dynamic lead numbers roll forward on publication day; require the issue,
    # selected period, and map URL to remain stable across the image download.
    checked_issue = parse_issue(get_text(SEASON_DISCUSSION))
    checked_image = parse_season_image(get_text(page_url), year, page_url)
    if checked_issue != issue or checked_image != image_url:
        raise ValueError("Seasonal outlook changed during download; refresh again")
    archived_discussion = CPC + f"/products/archives/long_lead/PMD/{issue.year}/{issue:%Y%m}_PMD90D"
    return {"name": "November–December–January", "observed_at": issue.isoformat(),
            "timestamp_precision": "date", "valid_period": f"Nov–Dec–Jan {year}–{str(year + 1)[-2:]}",
            "valid_start": context["season_start"], "valid_end": context["season_end"],
            "source_url": page_url, "discussion_url": archived_discussion,
            "image_url": image_url, "is_dated_archive": False,
            "selection": "Most recently issued NOAA seasonal temperature outlook",
            "publication_frequency": "Monthly",
            "methodology": "Three-month average temperature probabilities. Operational image bytes are saved together with the checked seasonal issue and selected valid period; no live-image fallback.",
            **snapshot}


def fetch(now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    context = requested_context(current)
    previous = date.fromisoformat(context["requested_previous_date"])
    result = {"source_url": CPC + "/products/forecasts/", "observed_at": None,
              "timestamp_precision": "date", **context, "previous_outlooks": [],
              "seasonal": {}, "warnings": [],
              "methodology": "Historical daily and weekly temperature images come only from NOAA dated archives. Previous day uses America/New_York. Weeks 3–4 is weekly, so its actual Friday issue date is retained. The latest November–January seasonal map is a separate monthly product, not a previous-day issuance."}
    discussion_url = SHORT_ARCHIVE + previous.strftime("%Y/%m/%d/") + f"PMDMRD.{previous:%Y%m%d}.txt"
    # One shared discussion request; each image failure is still isolated.
    def daily():
        discussion = get_text(discussion_url)
        products, warnings = [], []
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = {pool.submit(_short, previous, name, discussion): name for name in ("6–10 day", "8–14 day")}
            for future in as_completed(tasks):
                try:
                    products.append(future.result())
                except Exception as exc:
                    warnings.append(f"{tasks[future]} map for {previous} unavailable: {exc}")
        return products, warnings
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {pool.submit(daily): "daily", pool.submit(_weekly, previous): "Weeks 3–4",
                 pool.submit(_seasonal, context, current): "seasonal"}
        for future in as_completed(tasks):
            key = tasks[future]
            try:
                value = future.result()
                if key == "daily":
                    result["previous_outlooks"].extend(value[0])
                    result["warnings"].extend(value[1])
                elif key == "seasonal":
                    result["seasonal"] = value
                else:
                    result["previous_outlooks"].append(value)
                    if value.get("selection_warning"):
                        result["warnings"].append(value["selection_warning"])
            except Exception as exc:
                result["warnings"].append(f"NOAA {key} map unavailable: {exc}")
    order = {"6–10 day": 0, "8–14 day": 1, "Weeks 3–4": 2}
    result["previous_outlooks"].sort(key=lambda product: order[product["name"]])
    dates = [product["observed_at"] for product in result["previous_outlooks"]]
    if result["seasonal"]:
        dates.append(result["seasonal"]["observed_at"])
    result["observed_at"] = max(dates) if dates else None
    return result
