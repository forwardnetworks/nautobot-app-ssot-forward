"""Turn a Forward failure into a category, a plain reason and next steps.

A hard failure used to reach the operator as ``error: ForwardClientError: <raw
message>``. That tells a developer what threw but not an operator what to do.
This maps the failure to one of a small set of categories and attaches the
checks most likely to resolve it.

Classification prefers the SDK's own exception type, carried on
``ForwardClientError.kind``, and falls back to Forward's execution ``outcome``
and then to message text. Text matching is last because it is the least stable.

Pure and import-light on purpose: it runs inside the failure-recording path, so
it must not be able to raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FailureExplanation:
    category: str
    summary: str
    next_steps: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "summary": self.summary,
            "next_steps": list(self.next_steps),
        }

    def one_line(self) -> str:
        step = self.next_steps[0] if self.next_steps else ""
        return f"{self.category}: {self.summary} Next: {step}".strip()


_BY_KIND: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ForwardAuthError": (
        "authentication",
        "Forward rejected the credentials.",
        (
            "Check the username and password on the connection profile.",
            "Confirm the account can sign in to the Forward UI and is not locked.",
        ),
    ),
    "ForwardPermissionError": (
        "permission",
        "Forward accepted the credentials but refused this action.",
        (
            "Give the Forward account access to the network and to NQE.",
            "Check whether the action needs a role the account does not hold.",
        ),
    ),
    "ForwardRateLimitError": (
        "rate-limited",
        "Forward is limiting this account's request rate.",
        (
            "Wait before re-running; Forward can lock the user out for up to an hour.",
            "Raise the minimum request interval on the profile and avoid parallel runs.",
        ),
    ),
    "ForwardNqeQueryError": (
        "query-error",
        "Forward could not compile or run the NQE query.",
        (
            "Re-publish the bundled queries and audit them against the committed source.",
            "Check that the Forward release supports the query's syntax.",
        ),
    ),
    "ForwardNotFoundError": (
        "not-found",
        "Forward does not have the network, snapshot, or query that was asked for.",
        (
            "Check the network ID and snapshot setting on the profile.",
            "If a query is missing, publish the bundled queries.",
        ),
    ),
    "ForwardServerError": (
        "forward-server",
        "Forward returned a server error.",
        (
            "Retry later; this is usually transient on the Forward side.",
            "If it persists, check Forward's own health and logs.",
        ),
    ),
    "ForwardTimeoutError": (
        "timeout",
        "Forward did not finish within the allowed time.",
        (
            "Narrow the device scope or run during a quieter period.",
            "Raise the profile's timeout if the network is large.",
        ),
    ),
    "ForwardTransportError": (
        "network",
        "The connection to Forward failed before a response arrived.",
        (
            "Check DNS, routing, proxy and firewall between Nautobot and Forward.",
            "If the server uses a private CA, check the TLS verification setting.",
        ),
    ),
    "ForwardPaginationError": (
        "pagination",
        "Forward returned pages the client could not trust.",
        ("Re-run; if it repeats, capture the support bundle and report it.",),
    ),
    "ForwardResponseError": (
        "unexpected-response",
        "Forward answered in a shape the client did not expect.",
        (
            "Check the Forward release against the supported range.",
            "Capture the support bundle and report it.",
        ),
    ),
}

_BY_OUTCOME: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "SYSTEM_ERROR": (
        "nqe-system-error",
        "Forward's query engine failed internally, even after resubmission.",
        (
            "Re-run later; this is usually transient on the Forward side.",
            "If it persists on one slice, report that slice's query to Forward.",
        ),
    ),
    "TIMED_OUT": (
        "nqe-timeout",
        "The NQE query exceeded its execution time limit.",
        ("Narrow the device scope, or run against a smaller snapshot.",),
    ),
    "USER_ERROR": (
        "query-error",
        "The NQE query itself failed.",
        ("Re-publish the bundled queries and audit them against the committed source.",),
    ),
    "NO_SNAPSHOT": (
        "no-snapshot",
        "The Forward network has no processed snapshot to read.",
        ("Collect and process a snapshot in Forward, or pin a specific snapshot ID.",),
    ),
}

_TEXT: tuple[tuple[str, tuple[str, str, tuple[str, ...]]], ...] = (
    (
        "no latest processed snapshot",
        (
            "no-snapshot",
            "The Forward network has no processed snapshot to read.",
            ("Collect and process a snapshot in Forward, or pin a specific snapshot ID.",),
        ),
    ),
    (
        "certificate",
        (
            "tls",
            "The TLS certificate for Forward could not be verified.",
            ("Install the issuing CA on the Nautobot host, or correct the profile's URL.",),
        ),
    ),
)

_CONFIGURATION = (
    "configuration",
    "The profile or job settings are incomplete or inconsistent.",
    ("Open the connection profile and fix the setting named in the error.",),
)

_UNKNOWN = (
    "unknown",
    "The failure did not match a known Forward error.",
    ("Download the support bundle and report the error text with it.",),
)


def explain_failure(exc: BaseException) -> FailureExplanation:
    """Explain ``exc``; never raises."""
    try:
        return _explain(exc)
    except Exception:  # noqa: BLE001 - this runs while recording another failure
        return FailureExplanation(*_UNKNOWN)


def _explain(exc: BaseException) -> FailureExplanation:
    kind = str(getattr(exc, "kind", None) or type(exc).__name__)
    outcome = str(getattr(exc, "outcome", None) or "").upper()
    message = str(exc).lower()

    # The outcome is the more specific signal when an execution failed.
    if outcome in _BY_OUTCOME:
        return FailureExplanation(*_BY_OUTCOME[outcome])
    if kind in _BY_KIND:
        return FailureExplanation(*_BY_KIND[kind])
    for needle, found in _TEXT:
        if needle in message:
            return FailureExplanation(*found)
    if "ForwardConfigurationError" in (kind, type(exc).__name__):
        return FailureExplanation(*_CONFIGURATION)
    return FailureExplanation(*_UNKNOWN)
