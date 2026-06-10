"""DiffSync model classes for the first Forward ingestion slices."""

from __future__ import annotations

try:
    from diffsync import DiffSyncModel
except ModuleNotFoundError:  # pragma: no cover - local scaffold import path
    class DiffSyncModel:  # type: ignore[too-many-ancestors]
        """Fallback model base when DiffSync is not installed."""


class ForwardLocation(DiffSyncModel):
    _modelname = "locations"
    _identifiers = ("name",)
    _attributes = ("city", "country")

    name: str
    city: str = ""
    country: str = ""


class ForwardPlatform(DiffSyncModel):
    _modelname = "platforms"
    _identifiers = ("name",)
    _attributes = ("manufacturer", "device_type")

    name: str
    manufacturer: str = ""
    device_type: str = ""


class ForwardDeviceType(DiffSyncModel):
    _modelname = "device_types"
    _identifiers = ("name",)
    _attributes = ("color",)

    name: str
    color: str = "9e9e9e"


class ForwardDevice(DiffSyncModel):
    _modelname = "devices"
    _identifiers = ("name",)
    _attributes = ("location", "vendor", "model", "device_type")

    name: str
    location: str = ""
    vendor: str = ""
    model: str = ""
    device_type: str = ""

