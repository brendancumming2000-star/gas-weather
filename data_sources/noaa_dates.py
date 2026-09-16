"""Calendar convention for selecting NOAA's previous-day publications."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from storage.database import utcnow


def previous_noaa_date(now=None):
    return ((now or utcnow()).astimezone(ZoneInfo('America/New_York')).date()
            - timedelta(days=1)).isoformat()
