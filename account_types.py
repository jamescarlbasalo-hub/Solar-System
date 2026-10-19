"""Role-specific account classes used by SchoolSync's event workflow.

The role subclasses inherit common account data and behavior from
UserAccount. They override the event-status method so the event route can
apply role-specific rules through one shared interface.
"""


class UserAccount:
    """Shared, read-only view of an account record."""

    def __init__(self, record):
        self.__record = dict(record)

    @property
    def id(self):
        return self.__record["id"]

    @property
    def role(self):
        return self.__record["role"]

    def initial_event_status(self):
        """Default role behavior: accounts cannot submit events."""
        raise PermissionError("This account type cannot submit events.")


class AdminAccount(UserAccount):
    """An Admin's submitted event is published immediately."""

    def initial_event_status(self):
        return "Approved"


class StaffAccount(UserAccount):
    """A Staff member's event must be reviewed by an Admin."""

    def initial_event_status(self):
        return "Pending"


class StudentAccount(UserAccount):
    """Students can view events but the system does not let them submit."""


def account_from_record(record):
    """Build the appropriate child class for a stored account dictionary."""
    account_types = {
        "admin": AdminAccount,
        "staff": StaffAccount,
        "student": StudentAccount,
    }
    try:
        account_type = account_types[record["role"]]
    except (KeyError, TypeError):
        raise ValueError("Cannot create an account object for an unknown role.") from None
    return account_type(record)
