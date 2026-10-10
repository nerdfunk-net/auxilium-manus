"""Redaction corpus: realistic config lines from several vendors; the secret must not survive.

A line that is not recognised is a false negative, the risk the design accepts least
(doc/ai_integration/AI_ASSISTANT.md §4.3). Add a case here whenever a new leak is found.
"""

from __future__ import annotations

import pytest

from services.ai_assistant.redaction import Redactor

# (vendor, config text, secret value that must not appear in the redacted text)
CORPUS: list[tuple[str, str, str]] = [
    ("ios", "enable secret 9 $9$Zr2kQ1xPq7aB3c", "$9$Zr2kQ1xPq7aB3c"),
    ("ios", "enable password S3cretEnablePw", "S3cretEnablePw"),
    ("ios", "username admin privilege 15 secret 5 $1$abcd$EfGhIjKlMnOp", "$1$abcd$EfGhIjKlMnOp"),
    ("ios", "username ops password 7 094F471A1A0A", "094F471A1A0A"),
    ("ios", " password 7 0822455D0A16", "0822455D0A16"),
    ("ios", "tacacs-server host 10.1.1.5 key 7 0235015C0A", "0235015C0A"),
    ("ios", "radius-server host 10.1.1.6 auth-port 1812 key RadiusKey123", "RadiusKey123"),
    ("ios", "snmp-server community PublicRO123 RO", "PublicRO123"),
    (
        "ios",
        "snmp-server user bob grp v3 auth sha AuthPassw0rdXyz priv aes 128 PrivPassw0rd9",
        "AuthPassw0rdXyz",
    ),
    ("ios", " ip ospf message-digest-key 1 md5 7 OspfDigest0123", "OspfDigest0123"),
    ("ios", " ip ospf authentication-key OspfPlain99", "OspfPlain99"),
    ("ios", "ntp authentication-key 1 md5 NtpKeyValue01", "NtpKeyValue01"),
    ("ios", " standby 1 authentication md5 key-string HsrpSecret77", "HsrpSecret77"),
    ("ios", "crypto isakmp key VpnPreShared123 address 203.0.113.9", "VpnPreShared123"),
    ("ios", " neighbor 192.0.2.1 password BgpNeighborPw1", "BgpNeighborPw1"),
    ("ios", " pre-shared-key local 0 IkePsk1234", "IkePsk1234"),
    ("ios", " ppp chap password 0 ChapPw12345", "ChapPw12345"),
    ("ios", " wpa-psk ascii 0 WifiPassphrase99", "WifiPassphrase99"),
    ("ios", " key-string 7 1511021F0725", "1511021F0725"),
    (
        "nxos",
        "username admin password 5 $5$abcdefgh$IjKlMnOpQrSt role network-admin",
        "$5$abcdefgh$IjKlMnOpQrSt",
    ),
    (
        "nxos",
        "snmp-server user admin network-admin auth md5 0xAbCdEf0123456789 "
        "priv 0xFeDcBa9876543210 localizedkey",
        "0xAbCdEf0123456789",
    ),
    (
        "eos",
        "enable secret sha512 $6$saltsalt$HashHashHashHashHash",
        "$6$saltsalt$HashHashHashHashHash",
    ),
    (
        "eos",
        "username ops privilege 15 role network-admin secret sha512 $6$s$abcdefghijkl",
        "$6$s$abcdefghijkl",
    ),
    ("eos", "snmp-server community CommunityEos RO", "CommunityEos"),
    (
        "junos",
        'encrypted-password "$6$randomsalt$longhashvaluehere";',
        "$6$randomsalt$longhashvaluehere",
    ),
    ("junos", 'authentication-key "$9$Qw2/Cp0RhSeX7";', "$9$Qw2/Cp0RhSeX7"),
    ("junos", 'secret "$9$abcDEF123-xyz";', "$9$abcDEF123-xyz"),
    ("junos", "community SnmpCommJunos { authorization read-only; }", "SnmpCommJunos"),
    ("junos", 'pre-shared-key ascii-text "$9$IkePskJunos";', "$9$IkePskJunos"),
    ("generic", "password: Hunter2Hunter2", "Hunter2Hunter2"),
    ("generic", 'api_key = "sk-live-abcdef1234567890"', "sk-live-abcdef1234567890"),
    ("generic", "Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
    ("generic", "token=ghp_abcdefghijklmnopqrstuvwx", "ghp_abcdefghijklmnopqrstuvwx"),
    (
        "generic",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxyz\n-----END RSA PRIVATE KEY-----",
        "MIIEowIBAAKCAQEAxyz",
    ),
]


@pytest.mark.parametrize(
    ("vendor", "text", "secret"), CORPUS, ids=[f"{v}-{i}" for i, (v, _, _) in enumerate(CORPUS)]
)
def test_secret_does_not_survive_redaction(vendor: str, text: str, secret: str) -> None:
    redacted = Redactor().redact(text)

    assert secret not in redacted, redacted


def test_redaction_keeps_the_config_structure_readable() -> None:
    text = "interface Gi0/1\n description uplink\n ip address 10.0.0.1 255.255.255.0\n"

    assert Redactor().redact(text) == text


def test_every_redacted_secret_round_trips() -> None:
    redactor = Redactor()
    text = "enable secret 9 $9$Zr2kQ1xPq7aB3c\nsnmp-server community PublicRO123 RO\n"

    assert redactor.restore(redactor.redact(text)) == text
