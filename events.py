from datetime import date as date_cls, datetime, timedelta, timezone

from store import store
from models import get_user_by_id

VALID_STATUSES = ("Pending", "Approved", "Rejected")
SCHOOL_TIMEZONE = timezone(timedelta(hours=8))


def school_today():
    return datetime.now(SCHOOL_TIMEZONE).date()


def create_event(title, date, start_time, end_time, location, description, created_by, status):
    creator = get_user_by_id(created_by)
    if creator is None:
        raise ValueError("Cannot create an event for an account that does not exist.")
    event = store.add("events", {
        "title": title, "date": date, "start_time": start_time, "end_time": end_time,
        "location": location, "description": description, "created_by": created_by,
        "created_by_name": creator["name"], "created_by_role": creator["role"],
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return event["id"]


def get_event_by_id(event_id):
    return store.get("events", event_id)


def get_events_by_month(year, month):
    month_start = date_cls(year, month, 1).isoformat()
    month_end = (date_cls(year + 1, 1, 1) if month == 12
                 else date_cls(year, month + 1, 1)).isoformat()
    return sorted((event for event in store.all("events")
                   if month_start <= event["date"] < month_end),
                  key=lambda event: (event["date"], event["start_time"]))


def get_events_by_date(date_str):
    return sorted((event for event in store.all("events") if event["date"] == date_str),
                  key=lambda event: event["start_time"])


def get_all_events():
    return sorted(store.all("events"),
                  key=lambda event: (event["date"], event["start_time"]), reverse=True)


def get_events_by_creator(user_id):
    return sorted((event for event in store.all("events") if event["created_by"] == user_id),
                  key=lambda event: event["date"], reverse=True)


def get_events_by_creator_roles(roles):
    allowed_roles = set(roles)
    return sorted((event for event in store.all("events")
                   if _event_creator_role(event) in allowed_roles),
                  key=lambda event: (event["date"], event["start_time"]), reverse=True)


def get_events_by_status(status):
    return sorted((event for event in store.all("events") if event["status"] == status),
                  key=lambda event: (event["date"], event["start_time"]))


def get_upcoming_approved_events(limit=5):
    today = school_today().isoformat()
    rows = (event for event in store.all("events")
            if event["status"] == "Approved" and event["date"] > today)
    return sorted(rows, key=lambda event: (event["date"], event["start_time"]))[:limit]


def get_todays_approved_events():
    today = school_today().isoformat()
    return sorted((event for event in store.all("events")
                   if event["status"] == "Approved" and event["date"] == today),
                  key=lambda event: event["start_time"])


def count_all_events():
    return len(store.all("events"))


def count_events_by_status(status):
    return sum(event["status"] == status for event in store.all("events"))


def update_event(event_id, title, date, start_time, end_time, location, description):
    return store.update("events", event_id, {
        "title": title, "date": date, "start_time": start_time, "end_time": end_time,
        "location": location, "description": description,
    }) is not None


def set_event_status(event_id, status):
    if status not in VALID_STATUSES:
        raise ValueError(f"'{status}' is not a valid event status.")
    return store.update("events", event_id, {"status": status}) is not None


def delete_event(event_id):
    return store.remove("events", event_id) is not None


def event_time_display(event):
    if event["start_time"] == "TBA" or event["end_time"] == "TBA":
        return "Time to be announced"

    def format_time(value):
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (TypeError, ValueError):
            return value
        return parsed.strftime("%I:%M %p").lstrip("0")

    return f"{format_time(event['start_time'])} – {format_time(event['end_time'])}"


def is_visible(event, user):
    if user["role"] == "admin":
        return True
    if event["status"] == "Approved":
        return True
    if user["role"] == "staff":
        return _event_creator_role(event) in ("staff", "admin")
    return False


def filter_visible(events, user):
    return [event for event in events if is_visible(event, user)]


def staff_can_manage(event):
    return _event_creator_role(event) in ("staff", "admin")


def _event_creator_role(event):
    if event.get("created_by_role"):
        return event["created_by_role"]
    creator = get_user_by_id(event.get("created_by"))
    return creator["role"] if creator else None


def can_edit(event, user):
    if user["role"] == "admin":
        return True
    return user["role"] == "staff" and staff_can_manage(event)


def can_delete(event, user):
    if user["role"] == "admin":
        return True
    return user["role"] == "staff" and staff_can_manage(event)


def can_moderate(event, user):
    if user["role"] == "admin":
        return True
    return user["role"] == "staff" and staff_can_manage(event)
