"""Attributes the interface-workflow mixins rely on."""

from __future__ import annotations

from services.nautobot.api_protocol import NautobotApi
from services.nautobot.devices.common import DeviceCommonService


class InterfaceOpsBase:
    nautobot: NautobotApi
    common: DeviceCommonService
