"""Per-request Cisco ACI (APIC) connection credentials."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AciCredentials:
    base_url: str
    username: str
    password: str
    timeout: float = 30.0
    verify_ssl: bool = True
    # Remote-user login domain. APIC expects ``apic:<domain>\<user>`` for non-local users.
    login_domain: str = ""

    @property
    def login_name(self) -> str:
        if self.login_domain:
            return f"apic:{self.login_domain}\\{self.username}"
        return self.username
