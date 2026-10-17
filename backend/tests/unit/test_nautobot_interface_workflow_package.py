"""interface_workflow is a package; its public import path and mixin layout are stable."""

from __future__ import annotations

from services.nautobot.devices import InterfaceManagerService
from services.nautobot.devices.interface_workflow.ip_ops import InterfaceIpOps
from services.nautobot.devices.interface_workflow.record_ops import InterfaceRecordOps
from services.nautobot.devices.interface_workflow.service import (
    InterfaceManagerService as ServiceClass,
)


def test_public_import_path_is_unchanged() -> None:
    assert InterfaceManagerService is ServiceClass


def test_service_inherits_both_mixins() -> None:
    assert issubclass(InterfaceManagerService, InterfaceIpOps)
    assert issubclass(InterfaceManagerService, InterfaceRecordOps)
