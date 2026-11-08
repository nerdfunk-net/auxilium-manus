"""Client data service (write + retention sweep) and its retention settings."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from models.client_data import ClientCollectionStatus, ClientIpRow
from services.client_data.client_data_service import ClientDataService


def _service() -> tuple[ClientDataService, MagicMock]:
    service = ClientDataService(MagicMock())
    repo = MagicMock()
    repo.purge_older_than.return_value = 7
    service.repository = repo
    return service, repo


def test_zero_or_negative_days_keeps_everything() -> None:
    service, repo = _service()

    assert service.purge_older_than_days(0) == 0
    assert service.purge_older_than_days(-1) == 0
    repo.purge_older_than.assert_not_called()


def test_positive_days_delegates_with_a_timezone_aware_cutoff() -> None:
    service, repo = _service()

    assert service.purge_older_than_days(30, batch_size=100) == 7

    assert repo.purge_older_than.call_args.args[0].tzinfo is not None
    assert repo.purge_older_than.call_args.kwargs == {"batch_size": 100}


def test_store_device_collection_stamps_now_and_passes_rows() -> None:
    service, repo = _service()
    row = ClientIpRow(ip_address="10.0.0.1")

    service.store_device_collection(
        session_id="run-1",
        device_name="sw1",
        device_ip="192.0.2.1",
        ip_rows=[row],
        mac_rows=[],
        hostname_rows=[],
        status=ClientCollectionStatus(arp_status="ok"),
        keep_sessions=3,
    )

    kwargs = repo.replace_device_collection.call_args.kwargs
    assert kwargs["session_id"] == "run-1"
    assert kwargs["ip_rows"] == [row]
    assert kwargs["keep_sessions"] == 3
    assert kwargs["collected_at"].tzinfo is not None


@pytest.mark.parametrize("session_id", ["", "x" * 37])
def test_store_device_collection_rejects_a_bad_session_id(session_id: str) -> None:
    service, _ = _service()

    with pytest.raises(ValueError, match="session_id"):
        service.store_device_collection(
            session_id=session_id,
            device_name="sw1",
            device_ip=None,
            ip_rows=[],
            mac_rows=[],
            hostname_rows=[],
            status=ClientCollectionStatus(),
            keep_sessions=5,
        )


def test_store_device_collection_requires_a_device_name() -> None:
    service, _ = _service()

    with pytest.raises(ValueError, match="device_name"):
        service.store_device_collection(
            session_id="run-1",
            device_name=" ",
            device_ip=None,
            ip_rows=[],
            mac_rows=[],
            hostname_rows=[],
            status=ClientCollectionStatus(),
            keep_sessions=5,
        )


def test_retention_settings_defaults_and_validation() -> None:
    from core.config import Settings

    defaults = Settings()
    assert defaults.client_data_keep_sessions == 5
    assert defaults.client_data_retention_days == 90

    with patch.dict("os.environ", {"CLIENT_DATA_KEEP_SESSIONS": "0"}):
        with pytest.raises(RuntimeError, match="CLIENT_DATA_KEEP_SESSIONS"):
            Settings()
    with patch.dict("os.environ", {"CLIENT_DATA_RETENTION_DAYS": "-1"}):
        with pytest.raises(RuntimeError, match="CLIENT_DATA_RETENTION_DAYS"):
            Settings()
    with patch.dict(
        "os.environ", {"CLIENT_DATA_KEEP_SESSIONS": "9", "CLIENT_DATA_RETENTION_DAYS": "0"}
    ):
        configured = Settings()
        assert (configured.client_data_keep_sessions, configured.client_data_retention_days) == (
            9,
            0,
        )


def test_uplink_threshold_setting_defaults_and_validation() -> None:
    from core.config import Settings

    assert Settings().client_data_uplink_mac_threshold == 10
    with patch.dict("os.environ", {"CLIENT_DATA_UPLINK_MAC_THRESHOLD": "0"}):
        with pytest.raises(RuntimeError, match="CLIENT_DATA_UPLINK_MAC_THRESHOLD"):
            Settings()
    with patch.dict("os.environ", {"CLIENT_DATA_UPLINK_MAC_THRESHOLD": "25"}):
        assert Settings().client_data_uplink_mac_threshold == 25


def test_the_service_uses_the_configured_uplink_threshold() -> None:
    from core.config import settings

    assert ClientDataService(MagicMock()).queries.uplink_threshold == (
        settings.client_data_uplink_mac_threshold
    )
    assert ClientDataService(MagicMock(), uplink_threshold=3).queries.uplink_threshold == 3


def test_max_rows_setting_defaults_and_validation() -> None:
    from core.config import Settings

    assert Settings().client_data_max_rows_per_table == 200_000
    with patch.dict("os.environ", {"CLIENT_DATA_MAX_ROWS_PER_TABLE": "0"}):
        with pytest.raises(RuntimeError, match="CLIENT_DATA_MAX_ROWS_PER_TABLE"):
            Settings()
    with patch.dict("os.environ", {"CLIENT_DATA_MAX_ROWS_PER_TABLE": "1"}):
        assert Settings().client_data_max_rows_per_table == 1


def _store(service: ClientDataService, *, ips: int, macs: int, **extra) -> None:
    from models.client_data import ClientCollectionStatus, ClientIpRow, ClientMacRow

    service.store_device_collection(
        session_id="s1",
        device_name="sw1",
        device_ip=None,
        ip_rows=[
            ClientIpRow(ip_address=f"10.0.0.{n + 1}", mac_address="aabb.ccdd.eeff")
            for n in range(ips)
        ],
        mac_rows=[
            ClientMacRow(mac_address=f"aabb.ccdd.{n:04x}", vlan="10", port="Gi1/0/1")
            for n in range(macs)
        ],
        hostname_rows=[],
        status=ClientCollectionStatus(),
        keep_sessions=5,
        **extra,
    )


@pytest.mark.parametrize(("ips", "macs", "table"), [(3, 1, "ARP"), (1, 3, "MAC")])
def test_the_service_rejects_a_table_above_the_cap_and_writes_nothing(ips, macs, table) -> None:
    from models.client_data import TooManyRowsError

    service = ClientDataService(MagicMock())
    service.repository = MagicMock()

    with pytest.raises(TooManyRowsError) as caught:
        _store(service, ips=ips, macs=macs, max_rows=2)

    assert caught.value.table == table
    service.repository.replace_device_collection.assert_not_called()


def test_the_service_accepts_a_table_exactly_at_the_cap_and_defaults_to_the_setting() -> None:
    from core.config import settings

    service = ClientDataService(MagicMock())
    service.repository = MagicMock()

    _store(service, ips=2, macs=2, max_rows=2)
    service.repository.replace_device_collection.assert_called_once()

    with patch.object(settings, "client_data_max_rows_per_table", 1):
        from models.client_data import TooManyRowsError

        with pytest.raises(TooManyRowsError):
            _store(service, ips=2, macs=0)
