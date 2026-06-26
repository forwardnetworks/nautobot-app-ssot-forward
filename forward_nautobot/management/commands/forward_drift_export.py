"""Export the change's SoT-vs-Forward drift via the SSoT-Forward DiffSync.

Runs the Forward source adapter (dry-run, no writes), reads the Forward-observed
VLAN SVIs, and writes the change-verification gate's `sot-diff.json` contract: the
branches whose payments-VLAN SVI the change intends but Forward has not observed.

This is the first-class emit point the gate consumes (agent/sot-diff.contract.md):
the plugin's own DiffSync source, not an external re-implementation.

    nautobot-server forward_drift_export --out reports/sot-diff.json \
        --network 101 --vid 201 --branches br1,br2,br3,br4

Forward connection comes from the flags or FORWARD_API_BASE_URL/KEY/SECRET.
"""

from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand

from forward_nautobot.integrations.forward.jobs import _run_ingestion_plan


class Command(BaseCommand):
    help = "Emit the change's Forward-observed VLAN drift as the gate's sot-diff.json"

    def add_arguments(self, parser):
        parser.add_argument("--out", default="reports/sot-diff.json")
        parser.add_argument(
            "--network", default=os.environ.get("FORWARD_DEFAULT_NETWORK_ID", "101")
        )
        parser.add_argument("--vid", type=int, default=201)
        parser.add_argument("--change", default="CHG-ENT-00042")
        parser.add_argument("--branches", default="br1,br2,br3,br4")
        parser.add_argument(
            "--base-url",
            default=os.environ.get("FORWARD_API_BASE_URL", "https://ingress.local:30443"),
        )
        parser.add_argument("--username", default=os.environ.get("FORWARD_API_KEY", "admin"))
        parser.add_argument("--password", default=os.environ.get("FORWARD_API_SECRET", "forward"))
        parser.add_argument("--verify-tls", action="store_true")

    def handle(self, *args, **opts):
        _result, plan, _exec = _run_ingestion_plan(
            dryrun=True,
            base_url=opts["base_url"],
            username=opts["username"],
            password=opts["password"],
            network_id=str(opts["network"]),
            verify_tls=bool(opts["verify_tls"]),
            snapshot_id="latestProcessed",
            selected_models="interfaces",
        )
        recs = plan.source.records.get("interfaces", {})
        svi = f"vlan{opts['vid']}"
        observed = sorted(
            {
                key.split("|")[0]
                for key in recs
                if key.split("|")[-1].lower() == svi and key.split("|")[0].startswith("br")
            }
        )
        intent = [b.strip() for b in opts["branches"].split(",") if b.strip()]
        missing = [b for b in intent if b not in observed]
        snapshot = str(plan.reports[0].snapshot_id) if getattr(plan, "reports", None) else ""

        diff = {
            "schemaVersion": "1.0",
            "source": "nautobot-ssot-forward",
            "method": (
                "SSoT-Forward DiffSync source adapter — Forward-observed VLAN SVIs "
                "vs change intent (forward_drift_export management command)"
            ),
            "snapshotPair": {"preSnapshotId": "", "postSnapshotId": snapshot},
            "scope": {"changeId": opts["change"], "locations": intent},
            "slices": {
                "vlans": {
                    "create": [{"site": b, "vid": opts["vid"]} for b in missing],
                    "update": [],
                    "delete": [],
                },
                "interfaces": {"create": [], "update": [], "delete": []},
                "ipv4_prefixes": {"create": [], "update": [], "delete": []},
            },
            "summary": {"create": len(missing), "update": 0, "delete": 0},
        }
        out = opts["out"]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        json.dump(diff, open(out, "w"), indent=2)
        self.stdout.write(
            f"forward_drift_export: observed={observed} intent={intent} -> "
            f"vlans.create={missing} (snapshot {snapshot}); wrote {out}"
        )
