#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forward_nautobot.integrations.forward.queries import (
    QUERY_CONTRACT_FIELDS,
    QUERY_CONTRACT_VERSIONS,
    QUERY_FILENAMES,
    get_query_contract_field_sets,
    read_bundled_query_execution_source,
    read_bundled_query_source,
)


def main() -> int:
    failures: list[str] = []
    for filename in QUERY_FILENAMES:
        saved_source = read_bundled_query_source(filename)
        execution_source = read_bundled_query_execution_source(filename)
        if saved_source.count("@primaryKey(") != 1:
            failures.append(f"{filename}: saved source must declare exactly one @primaryKey")
        if "@query" in saved_source:
            failures.append(f"{filename}: saved source must remain unparameterized")
        if "@primaryKey" in execution_source:
            failures.append(f"{filename}: inline source retained saved-query metadata")
        if execution_source.rstrip().endswith(";"):
            failures.append(f"{filename}: final inline expression must not end with a semicolon")
        expected = QUERY_CONTRACT_FIELDS[filename]
        field_sets = get_query_contract_field_sets(filename)
        if not field_sets:
            failures.append(
                f"{filename}: no contract fields could be parsed from the bundled query"
            )
            continue
        if expected not in field_sets:
            failures.append(
                f"{filename}: no parsed result shape matches the expected bundle contract"
            )
        if not QUERY_CONTRACT_VERSIONS.get(filename):
            failures.append(f"{filename}: missing contract version header")
    if failures:
        print("Query contract check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Query contract check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
