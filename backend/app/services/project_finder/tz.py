"""Working-hours overlap between you and a foreign client (default: relative to Asia/Kolkata).

Computed on a concrete date so daylight-saving shifts are respected (US/EU clients move by an hour
twice a year, which changes the overlap with India)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SLOT_MIN = 30

# Convenience guesses for the form; large countries span several zones, so this is only a suggestion.
COUNTRY_TZ = {
    "united states": "America/New_York", "usa": "America/New_York", "us": "America/New_York",
    "canada": "America/Toronto", "mexico": "America/Mexico_City", "brazil": "America/Sao_Paulo",
    "united kingdom": "Europe/London", "uk": "Europe/London", "ireland": "Europe/Dublin",
    "germany": "Europe/Berlin", "france": "Europe/Paris", "spain": "Europe/Madrid", "italy": "Europe/Rome",
    "netherlands": "Europe/Amsterdam", "sweden": "Europe/Stockholm", "norway": "Europe/Oslo",
    "denmark": "Europe/Copenhagen", "switzerland": "Europe/Zurich", "poland": "Europe/Warsaw",
    "united arab emirates": "Asia/Dubai", "uae": "Asia/Dubai", "saudi arabia": "Asia/Riyadh",
    "singapore": "Asia/Singapore", "japan": "Asia/Tokyo", "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland", "south africa": "Africa/Johannesburg", "india": "Asia/Kolkata",
}  # fmt: skip


def suggest_timezone(country: str) -> str:
    return COUNTRY_TZ.get(country.strip().lower(), "")


def _offset(dt: datetime) -> str:
    off = dt.utcoffset() or timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    return f"{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _working(dt: datetime, start: int, end: int) -> bool:
    h = dt.hour + dt.minute / 60
    return start <= h < end


def overlap(
    home_tz: str,
    client_tz: str,
    *,
    start_hour: int = 9,
    end_hour: int = 18,
    on: date | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Shared working hours on date `on` (default today in `home_tz`), assuming `start_hour`-`end_hour`
    local time on both sides. Raises ZoneInfoNotFoundError for an unknown zone."""
    home, client = ZoneInfo(home_tz), ZoneInfo(client_tz)
    now = (now or datetime.now(UTC)).astimezone(UTC)
    day = on or now.astimezone(home).date()
    t0 = datetime.combine(day, time(0, 0), tzinfo=home).astimezone(UTC)

    windows: list[tuple[datetime, datetime]] = []
    for i in range(24 * 60 // SLOT_MIN):
        slot = t0 + timedelta(minutes=SLOT_MIN * i)
        h, c = slot.astimezone(home), slot.astimezone(client)
        if _working(h, start_hour, end_hour) and _working(c, start_hour, end_hour):
            end = slot + timedelta(minutes=SLOT_MIN)
            if windows and windows[-1][1] == slot:
                windows[-1] = (windows[-1][0], end)
            else:
                windows.append((slot, end))

    hours = sum((e - s).total_seconds() for s, e in windows) / 3600
    rating = (
        "good" if hours >= 4 else "workable" if hours >= 2 else "limited" if hours > 0 else "none"
    )
    # Offsets describe the requested day (so DST dates are right); the clocks describe right now.
    ref = now if on is None else t0 + timedelta(hours=12)
    home_ref, client_ref = ref.astimezone(home), ref.astimezone(client)
    diff = (
        (client_ref.utcoffset() or timedelta(0)) - (home_ref.utcoffset() or timedelta(0))
    ).total_seconds() / 3600
    c_midnight = datetime.combine(day, time(0, 0), tzinfo=client)
    cs = (c_midnight + timedelta(hours=start_hour)).astimezone(home)
    ce = (c_midnight + timedelta(hours=end_hour)).astimezone(home)
    their_day = f"{_hhmm(cs)}-{_hhmm(ce)}" + (" (next day)" if ce.date() != cs.date() else "")
    notes = {
        "good": "Plenty of shared working hours - live calls are easy.",
        "workable": "A couple of shared hours - book calls inside the window and work async the rest.",
        "limited": "Very little overlap - keep calls short and agree on async updates.",
        "none": f"No shared working hours. Their {start_hour:02d}:00-{end_hour:02d}:00 is {their_day} for you; "
        "offer one scheduled call in your evening/early morning and work async otherwise.",
    }
    return {
        "home_tz": home_tz,
        "client_tz": client_tz,
        "home_offset": _offset(home_ref),
        "client_offset": _offset(client_ref),
        "difference_hours": diff,
        "overlap_hours": round(hours, 1),
        "windows": [
            {
                "home_start": _hhmm(s.astimezone(home)),
                "home_end": _hhmm(e.astimezone(home)),
                "client_start": _hhmm(s.astimezone(client)),
                "client_end": _hhmm(e.astimezone(client)),
            }
            for s, e in windows
        ],  # fmt: skip
        "rating": rating,
        "note": notes[rating],
        "home_now": now.astimezone(home).strftime("%a %H:%M"),
        "client_now": now.astimezone(client).strftime("%a %H:%M"),
        "client_day_in_home_time": their_day,
        "hours": f"{start_hour:02d}:00-{end_hour:02d}:00",
    }
