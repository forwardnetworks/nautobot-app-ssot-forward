"""Forward integration exceptions."""


class ForwardError(Exception):
    """Base error for the Forward Nautobot integration."""


class ForwardConfigurationError(ForwardError):
    """Raised when required sync configuration is missing or invalid."""


class ForwardClientError(ForwardError):
    """Raised when Forward API communication fails.

    The optional attributes carry what the SDK knew about the failure so a job
    result or support bundle can explain it without re-parsing the message:
    ``reason`` is the SDK's structured reason, ``outcome`` is Forward's own term
    for a failed execution (``SYSTEM_ERROR``, ``TIMED_OUT``, ``USER_ERROR``),
    ``detail`` is Forward's error object, and ``attempts`` is how many times the
    SDK submitted the query after an execution failure, or how many HTTP sends it
    made after a transport failure.
    """

    #: Name of the SDK exception this wraps (e.g. ``ForwardAuthError``), if any.
    kind: str | None = None
    reason: str | None = None
    outcome: str | None = None
    detail: object = None
    attempts: int | None = None


class ForwardSyncError(ForwardError):
    """Raised when the Forward sync runner cannot complete a request."""
