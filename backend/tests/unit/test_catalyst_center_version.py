"""Tests for Catalyst Center release parsing and capability gating."""

from __future__ import annotations

import pytest

from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.common.version import (
    CatalystCenterRelease,
    parse_release,
    release_from_payload,
)


class TestParseRelease:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2.3.7.9", (2, 3, 7, 9)),
            ("2.3.7.9-70050", (2, 3, 7, 9)),
            ("2.3.3.6", (2, 3, 3, 6)),
            ("3.1.6", (3, 1, 6, 0)),
            ("3.3.1", (3, 3, 1, 0)),
            ("  2.3.5.3  ", (2, 3, 5, 3)),
        ],
    )
    def test_parses_known_shapes(self, raw, expected):
        release = parse_release(raw)
        assert release.as_tuple() == expected
        assert release.raw == raw.strip()

    @pytest.mark.parametrize("raw", ["", "abc", "2.3", "v2", None])
    def test_rejects_unparseable(self, raw):
        with pytest.raises(CatalystCenterValidationError):
            parse_release(raw)


class TestCapabilities:
    def test_filtered_count_needs_2_3_7(self):
        assert not parse_release("2.3.3.6").supports_filtered_device_count
        assert not parse_release("2.3.5.3").supports_filtered_device_count
        assert parse_release("2.3.7.9").supports_filtered_device_count
        assert parse_release("3.1.6").supports_filtered_device_count

    def test_ordering(self):
        assert parse_release("2.3.7.9") > parse_release("2.3.7.6")
        assert parse_release("3.1.6") > parse_release("2.3.7.9")

    def test_is_immutable(self):
        release = parse_release("2.3.7.9")
        with pytest.raises(AttributeError):
            release.major = 9  # type: ignore[misc]


class TestReleaseFromPayload:
    def test_reads_installed_version(self):
        payload = {"response": {"installedVersion": "2.3.7.9-70050"}, "version": "1.0"}
        assert release_from_payload(payload) == CatalystCenterRelease(2, 3, 7, 9, "2.3.7.9-70050")

    def test_falls_back_to_version_key(self):
        payload = {"response": {"version": "3.1.6"}}
        assert release_from_payload(payload).as_tuple() == (3, 1, 6, 0)

    @pytest.mark.parametrize("payload", [{}, {"response": {}}, {"response": "x"}, []])
    def test_missing_version_raises(self, payload):
        with pytest.raises(CatalystCenterValidationError):
            release_from_payload(payload)
