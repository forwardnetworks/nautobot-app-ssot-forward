"""Failure explanations: a category and a next step for every way Forward can fail."""

import pytest

from forward_nautobot.integrations.forward.exceptions import (
    ForwardClientError,
    ForwardConfigurationError,
)
from forward_nautobot.integrations.forward.explain import explain_failure


def _client_error(message="boom", **attrs):
    err = ForwardClientError(message)
    for key, value in attrs.items():
        setattr(err, key, value)
    return err


@pytest.mark.parametrize(
    ("kind", "category"),
    [
        ("ForwardAuthError", "authentication"),
        ("ForwardPermissionError", "permission"),
        ("ForwardRateLimitError", "rate-limited"),
        ("ForwardNqeQueryError", "query-error"),
        ("ForwardNotFoundError", "not-found"),
        ("ForwardServerError", "forward-server"),
        ("ForwardTimeoutError", "timeout"),
        ("ForwardTransportError", "network"),
        ("ForwardPaginationError", "pagination"),
        ("ForwardResponseError", "unexpected-response"),
        ("ForwardConfigurationError", "configuration"),
    ],
)
def test_each_sdk_failure_kind_has_a_category_and_a_next_step(kind, category):
    explanation = explain_failure(_client_error(kind=kind))
    assert explanation.category == category
    assert explanation.summary
    assert explanation.next_steps, "an operator must always be told what to check next"


def test_execution_outcome_wins_over_the_exception_type():
    err = _client_error(kind="ForwardExecutionError", outcome="SYSTEM_ERROR", attempts=3)
    assert explain_failure(err).category == "nqe-system-error"
    assert explain_failure(_client_error(outcome="TIMED_OUT")).category == "nqe-timeout"


def test_missing_snapshot_is_recognised_from_the_message():
    err = _client_error("Forward network net-1 has no latest processed snapshot.")
    assert explain_failure(err).category == "no-snapshot"


def test_no_snapshot_outcome_is_recognised():
    err = _client_error(kind="ForwardExecutionError", outcome="NO_SNAPSHOT")
    assert explain_failure(err).category == "no-snapshot"


def test_unrecognised_outcome_is_not_mistaken_for_a_transient_failure():
    err = _client_error(kind="ForwardExecutionError", outcome="SOME_FUTURE_STATE")
    assert explain_failure(err).category == "unknown"


def test_plugin_configuration_error_is_a_configuration_failure():
    assert explain_failure(ForwardConfigurationError("no query")).category == "configuration"


def test_unrecognised_failure_still_explains_itself_and_never_raises():
    assert explain_failure(RuntimeError("???")).category == "unknown"

    class _Hostile(Exception):
        def __str__(self):
            raise ValueError("cannot stringify")

    # The explainer runs while another failure is being recorded; it must not raise.
    assert explain_failure(_Hostile()).category == "unknown"


def test_one_line_form_leads_with_the_category_and_first_step():
    line = explain_failure(_client_error(kind="ForwardAuthError")).one_line()
    assert line.startswith("authentication:")
    assert "Next:" in line
