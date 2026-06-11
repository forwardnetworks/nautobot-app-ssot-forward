#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forward_nautobot.integrations.forward.queries import QUERY_CONTRACT_FIELDS
from forward_nautobot.integrations.forward.queries import QUERY_CONTRACT_VERSIONS
from forward_nautobot.integrations.forward.queries import QUERY_FILENAMES
from forward_nautobot.integrations.forward.queries import get_query_contract_field_sets


def main() -> int:
    failures: list[str] = []
    for filename in QUERY_FILENAMES:
        expected = QUERY_CONTRACT_FIELDS[filename]
        field_sets = get_query_contract_field_sets(filename)
        if not field_sets:
            failures.append(f"{filename}: no contract fields could be parsed from the bundled query")
            continue
        if any(field_set != expected for field_set in field_sets):
            failures.append(
                f"{filename}: parsed contract fields do not match the expected bundle contract"
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
