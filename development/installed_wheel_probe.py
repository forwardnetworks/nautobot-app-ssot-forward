"""Runtime acceptance probe executed inside the source-absent wheel image."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import nautobot

nautobot.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from nautobot.cloud.models import CloudAccount, CloudNetwork, CloudService  # noqa: E402

import forward_nautobot  # noqa: E402
from forward_nautobot.integrations.forward.contrib_sync import (  # noqa: E402
    cloud_account_identity,
    cloud_object_name,
    run_contrib_cloud_sync,
)
from forward_nautobot.integrations.forward.jobs import (  # noqa: E402
    ForwardInventoryDataSource,
    jobs,
)
from forward_nautobot.integrations.forward.queries import QUERY_FILENAMES  # noqa: E402
from forward_nautobot.models import ForwardConnectionProfile  # noqa: E402


def _assert_installed_wheel_boundary() -> None:
    module_path = Path(forward_nautobot.__file__).resolve()
    if "/source/" in f"{module_path}/" or Path("/source/forward_nautobot").exists():
        raise AssertionError(f"plugin resolved from repository source: {module_path}")
    if "site-packages" not in str(module_path):
        raise AssertionError(
            f"plugin did not resolve from an installed distribution: {module_path}"
        )


def _seed_generic_fixture() -> object:
    user_model = get_user_model()
    user, _created = user_model.objects.get_or_create(
        username="wheel-acceptance",
        defaults={"is_staff": True, "is_superuser": True, "is_active": True},
    )
    if not user.is_superuser or not user.is_staff:
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.save(update_fields=("is_superuser", "is_staff", "is_active"))
    ForwardConnectionProfile.objects.update_or_create(
        name="wheel-acceptance",
        defaults={
            "base_url": "https://example.invalid",
            "network_id": "fixture-network",
            "is_default": True,
            "last_support_bundle_json": json.dumps(
                {
                    "status": "fixture",
                    "mode": "preview",
                    "row_count": 0,
                    "diff_summary": {},
                    "diagnostics": {},
                }
            ),
        },
    )
    return user


def _assert_packaged_resources() -> None:
    query_root = resources.files("forward_nautobot.integrations.forward.queries")
    missing = [
        filename for filename in QUERY_FILENAMES if not query_root.joinpath(filename).is_file()
    ]
    if missing:
        raise AssertionError(f"installed wheel is missing bundled queries: {missing}")
    fixture = resources.files("forward_nautobot.fixtures").joinpath("forward_sample_ingestion.json")
    if not fixture.is_file():
        raise AssertionError("installed wheel is missing the sanitized ingestion fixture")


def _assert_routes(user: object) -> None:
    client = Client()
    client.force_login(user)
    routes = {
        "home": reverse("plugins:forward_nautobot:home"),
        "diagnostics": reverse("plugins:forward_nautobot:diagnostics"),
        "status": reverse("plugins:forward_nautobot:status"),
        "configuration": reverse("plugins:forward_nautobot:configuration"),
        "slice-detail": reverse(
            "plugins:forward_nautobot:slice-detail", kwargs={"model_slug": "devices"}
        ),
        "support-bundle": reverse("plugins:forward_nautobot:support-bundle-download"),
        "api-health": reverse("plugins-api:forward_nautobot-api:health"),
        "api-status": reverse("plugins-api:forward_nautobot-api:status"),
        "api-support-bundle": reverse("plugins-api:forward_nautobot-api:support-bundle"),
    }
    failures: list[str] = []
    for label, route in routes.items():
        response = client.get(route)
        if response.status_code != 200:
            failures.append(f"{label} {route}: HTTP {response.status_code}")
    if failures:
        raise AssertionError("installed-wheel route failures: " + "; ".join(failures))


def _assert_native_cloud_crud() -> None:
    """Exercise cloud create/update/relationships/delete safety transactionally."""

    account_rows = [
        {"account_id": "fixture-account", "name": "Fixture account", "cloud_type": "TYPE_A"}
    ]
    network_rows = [
        {
            "account_id": "fixture-account",
            "cloud_type": "TYPE_A",
            "network_id": "fixture-network",
            "name": "Fixture network",
            "parent_id": "",
            "kind": "vpc",
            "cidrs": ["10.250.0.0/16"],
        },
        {
            "account_id": "fixture-account",
            "cloud_type": "TYPE_A",
            "network_id": "fixture-subnet",
            "name": "Fixture subnet",
            "parent_id": "fixture-network",
            "kind": "subnet",
            "cidrs": ["10.250.1.0/24"],
        },
    ]
    service_rows = [
        {
            "account_id": "fixture-account",
            "cloud_type": "TYPE_A",
            "service_id": "fixture-service",
            "name": "Fixture service",
            "service_kind": "load-balancer",
            "vpc_id": "fixture-network",
        }
    ]
    identity = cloud_account_identity("TYPE_A", "fixture-account")
    account_name = cloud_object_name("account", "fixture-account", account_id="TYPE_A")
    vpc_name = cloud_object_name("network", "fixture-network", account_id=identity)
    subnet_name = cloud_object_name("network", "fixture-subnet", account_id=identity)
    service_name = cloud_object_name("service", "fixture-service", account_id=identity)
    if CloudAccount.objects.filter(name=account_name).exists():
        raise AssertionError("installed-wheel cloud fixture already exists")

    with transaction.atomic():
        run_contrib_cloud_sync(
            account_rows=account_rows,
            network_rows=network_rows,
            service_rows=service_rows,
            dryrun=False,
        )
        account = CloudAccount.objects.get(name=account_name)
        vpc = CloudNetwork.objects.get(name=vpc_name)
        subnet = CloudNetwork.objects.get(name=subnet_name)
        service = CloudService.objects.get(name=service_name)
        if subnet.parent_id != vpc.pk:
            raise AssertionError("installed-wheel cloud subnet parent was not linked")
        if vpc.cloud_account_id != account.pk or subnet.cloud_account_id != account.pk:
            raise AssertionError("installed-wheel cloud network account was not linked")
        if service.cloud_account_id != account.pk:
            raise AssertionError("installed-wheel cloud service account was not linked")
        if vpc.prefixes.count() != 1 or subnet.prefixes.count() != 1:
            raise AssertionError("installed-wheel cloud prefixes were not linked")
        if not service.cloud_networks.filter(pk=vpc.pk).exists():
            raise AssertionError("installed-wheel cloud service network was not linked")

        vpc.extra_config = {
            "operator": {"owner": "platform"},
            "forward": {"operator_note": "keep"},
        }
        vpc.save()
        network_rows[0]["name"] = "Renamed fixture network"
        run_contrib_cloud_sync(
            account_rows=account_rows,
            network_rows=network_rows,
            service_rows=service_rows,
            dryrun=False,
        )
        vpc.refresh_from_db()
        if vpc.description != "Renamed fixture network":
            raise AssertionError("installed-wheel cloud display update failed")
        if vpc.extra_config.get("operator") != {"owner": "platform"}:
            raise AssertionError("installed-wheel cloud sync replaced operator metadata")
        if vpc.extra_config.get("forward", {}).get("operator_note") != "keep":
            raise AssertionError("installed-wheel cloud sync replaced nested metadata")

        removal = run_contrib_cloud_sync(
            account_rows=[], network_rows=[], service_rows=[], dryrun=False
        )
        if removal.get("delete_suppressed") != 4:
            raise AssertionError("installed-wheel cloud delete suppression was not reported")
        if not CloudAccount.objects.filter(pk=account.pk).exists():
            raise AssertionError("installed-wheel cloud delete suppression failed")
        transaction.set_rollback(True)

    if CloudAccount.objects.filter(name=account_name).exists():
        raise AssertionError("installed-wheel cloud fixture transaction did not roll back")


def main() -> int:
    _assert_installed_wheel_boundary()
    _assert_packaged_resources()
    if ForwardInventoryDataSource not in jobs:
        raise AssertionError("Forward SSoT DataSource is not registered from the installed wheel")
    user = _seed_generic_fixture()
    _assert_routes(user)
    _assert_native_cloud_crud()
    print(
        "Installed-wheel acceptance passed: "
        f"plugin={forward_nautobot.__version__} nautobot={nautobot.__version__}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
