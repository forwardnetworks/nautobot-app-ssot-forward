"""Forward integration exceptions."""


class ForwardError(Exception):
    """Base error for the Forward Nautobot integration."""


class ForwardConfigurationError(ForwardError):
    """Raised when required sync configuration is missing or invalid."""


class ForwardClientError(ForwardError):
    """Raised when Forward API communication fails."""


class ForwardSyncError(ForwardError):
    """Raised when the Forward sync runner cannot complete a request."""

