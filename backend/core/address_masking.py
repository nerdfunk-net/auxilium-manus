"""Reversible address masking for text that is sent to an AI model.

By default every IP address in such text becomes an opaque ``__ADDR_n__`` token
(``services/ai_assistant/redaction.py``). That hides the address but also every relationship
between addresses (same subnet, gateway inside the subnet), and the model's reply keeps the tokens.
This module offers two better, still reversible, ways to hide an address, chosen by the operator
(``AI_ADDRESS_MASKING``, ``AI_ADDRESS_MAP_FILE``):

* ``map``: an operator-written YAML file ``real_prefix: fake_prefix``. An address inside a listed
  real prefix is replaced by the address at the same position in the fake prefix (``140.1.0.5`` with
  ``140.1.0.0/24: 192.168.178.0/24`` becomes ``192.168.178.5``). Any other address is *not* handled
  here, so the caller tokenises it: nothing unmapped is ever sent.
* ``auto``: the file is optional; every address it does not cover is pseudonymised per request. The
  addresses are grouped by /24 (IPv4) or /64 (IPv6) and each group gets the next free block of a
  reserved pool (``198.18.0.0/15`` and ``2001:db8::/32``), keeping the position inside the block, so
  addresses that shared a subnet still share one. When the pool is used up the caller tokenises.

``AddressMasker.restore`` turns the fake addresses in a reply back into the real ones. It only
touches addresses inside a fake prefix of the file or inside a block this masker handed out; every
other address, every token and every secret is left alone.

Netmask- and wildcard-shaped values (``255.255.255.0``, ``0.0.0.255``) and ``0.0.0.0`` carry meaning
and identify nothing, so they pass through unchanged in ``map`` / ``auto`` mode.

This module imports nothing from the application (``core.config`` loads the file at startup).
"""

from __future__ import annotations

import ipaddress
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml

MODE_TOKENS = "tokens"
MODE_MAP = "map"
MODE_AUTO = "auto"
MODES = frozenset({MODE_TOKENS, MODE_MAP, MODE_AUTO})

# Reserved ranges the automatic mode hands out (benchmarking / documentation prefixes).
AUTO_POOL_V4 = ipaddress.ip_network("198.18.0.0/15")
AUTO_POOL_V6 = ipaddress.ip_network("2001:db8::/32")
AUTO_BLOCK_V4 = 24
AUTO_BLOCK_V6 = 64

MAX_MAP_FILE_BYTES = 256 * 1024
MAX_MAP_ENTRIES = 10_000

type Network = ipaddress.IPv4Network | ipaddress.IPv6Network
type Address = ipaddress.IPv4Address | ipaddress.IPv6Address


class AddressMapError(ValueError):
    """The address map file is missing, unreadable or not a valid, consistent mapping."""


def _parse_network(raw: object, role: str, line: str) -> Network:
    if not isinstance(raw, str):
        raise AddressMapError(f"{line}: the {role} prefix must be text, e.g. 10.0.0.0/24")
    try:
        return ipaddress.ip_network(raw.strip(), strict=True)
    except ValueError as exc:
        raise AddressMapError(f"{line}: {raw!r} is not a valid prefix ({exc})") from exc


def _start(network: Network) -> int:
    return int(network.network_address)


def _end(network: Network) -> int:
    return int(network.broadcast_address)


def _check_no_overlap(networks: Iterable[Network]) -> None:
    """Any two prefixes of one family that overlap (also source against target) are refused."""
    for version in (4, 6):
        ordered = sorted((n for n in networks if n.version == version), key=_start)
        # Sweep in start order against the prefix that reaches furthest so far.
        reach = None
        for network in ordered:
            if reach is not None and _start(network) <= _end(reach):
                raise AddressMapError(f"the prefixes {reach} and {network} overlap")
            if reach is None or _end(network) > _end(reach):
                reach = network


class AddressMap:
    """Validated ``real prefix -> fake prefix`` entries with fast lookup in both directions."""

    def __init__(self, entries: Iterable[tuple[Network, Network]]) -> None:
        self._entries: tuple[tuple[Network, Network], ...] = tuple(entries)
        if len(self._entries) > MAX_MAP_ENTRIES:
            raise AddressMapError(f"the map has more than {MAX_MAP_ENTRIES} entries")
        for source, target in self._entries:
            if source.version != target.version:
                raise AddressMapError(f"{source}: {target} is not the same address family")
            if source.prefixlen != target.prefixlen:
                raise AddressMapError(
                    f"{source}: {target} has a different prefix length; both sides must match"
                )
        _check_no_overlap([net for pair in self._entries for net in pair])
        self._forward = self._index(self._entries, 0)
        self._backward = self._index(self._entries, 1)

    @staticmethod
    def _index(
        entries: tuple[tuple[Network, Network], ...], side: int
    ) -> dict[int, tuple[list[int], list[tuple[Network, Network]]]]:
        index: dict[int, tuple[list[int], list[tuple[Network, Network]]]] = {}
        for version in (4, 6):
            chosen = sorted(
                (e for e in entries if e[0].version == version), key=lambda e: _start(e[side])
            )
            index[version] = ([_start(e[side]) for e in chosen], chosen)
        return index

    @classmethod
    def from_mapping(cls, raw: Mapping[object, object]) -> AddressMap:
        entries = [
            (_parse_network(key, "real", str(key)), _parse_network(value, "fake", str(key)))
            for key, value in raw.items()
        ]
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def networks(self) -> tuple[Network, ...]:
        return tuple(net for pair in self._entries for net in pair)

    def _find(
        self,
        address: Address,
        index: dict[int, tuple[list[int], list[tuple[Network, Network]]]],
        side: int,
    ) -> tuple[Network, Network] | None:
        starts, chosen = index[address.version]
        position = bisect_right(starts, int(address)) - 1
        if position < 0:
            return None
        entry = chosen[position]
        return entry if address in entry[side] else None

    def to_fake(self, address: Address) -> Address | None:
        entry = self._find(address, self._forward, 0)
        if entry is None:
            return None
        source, target = entry
        return type(address)(_start(target) + int(address) - _start(source))

    def to_real(self, address: Address) -> Address | None:
        entry = self._find(address, self._backward, 1)
        if entry is None:
            return None
        source, target = entry
        return type(address)(_start(source) + int(address) - _start(target))


def _read_map_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_MAP_FILE_BYTES:
            raise AddressMapError(f"{path}: the file is larger than {MAX_MAP_FILE_BYTES} bytes")
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AddressMapError(f"{path}: cannot be read ({exc.strerror or exc})") from exc
    except UnicodeDecodeError as exc:
        raise AddressMapError(f"{path}: is not valid UTF-8 text") from exc


def _refuse_aliases(path: Path, text: str) -> None:
    """YAML aliases can expand a small file into a huge tree, and a prefix map never needs them."""
    try:
        for count, event in enumerate(yaml.parse(text), start=1):
            if isinstance(event, yaml.AliasEvent):
                raise AddressMapError(f"{path}: YAML aliases (*name) are not allowed")
            if count > 4 * MAX_MAP_ENTRIES + 16:
                raise AddressMapError(f"{path}: the file has too many entries")
    except yaml.YAMLError as exc:
        raise AddressMapError(f"{path}: is not valid YAML") from exc


def resolve_map_path(setting: str, data_directory: Path) -> Path:
    """The map file for ``AI_ADDRESS_MAP_FILE``. An absolute path is taken as given; a relative one
    must stay inside ``data_directory`` (``ai/../../.env`` is refused)."""
    candidate = Path(setting)
    if candidate.is_absolute():
        return candidate
    base = data_directory.resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise AddressMapError(f"{setting}: a relative path must stay inside the data directory")
    return resolved


def load_address_map(path: Path) -> AddressMap:
    """Read and validate the YAML map; every problem is an ``AddressMapError`` naming the file."""
    text = _read_map_text(path)
    _refuse_aliases(path, text)
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AddressMapError(f"{path}: is not valid YAML") from exc
    if raw is None:
        raise AddressMapError(f"{path}: the file is empty")
    if not isinstance(raw, dict):
        raise AddressMapError(f"{path}: expected 'real_prefix: fake_prefix' lines")
    try:
        return AddressMap.from_mapping(raw)
    except AddressMapError as exc:
        raise AddressMapError(f"{path}: {exc}") from exc


def validate_masking_config(mode: str, address_map: AddressMap | None) -> None:
    """Startup rules that depend on the mode (raises ``AddressMapError``)."""
    if mode not in MODES:
        raise AddressMapError(f"AI_ADDRESS_MASKING must be one of {', '.join(sorted(MODES))}")
    if mode == MODE_MAP and address_map is None:
        raise AddressMapError("AI_ADDRESS_MASKING=map needs AI_ADDRESS_MAP_FILE")
    if mode == MODE_TOKENS and address_map is not None:
        raise AddressMapError("AI_ADDRESS_MAP_FILE is set but AI_ADDRESS_MASKING is 'tokens'")
    if mode == MODE_AUTO and address_map is not None:
        # The automatic pool must not collide with real or fake prefixes of the file.
        for network in address_map.networks:
            for pool in (AUTO_POOL_V4, AUTO_POOL_V6):
                if network.version == pool.version and network.overlaps(pool):
                    raise AddressMapError(
                        f"the prefix {network} overlaps the automatic pool {pool}; "
                        "choose another prefix or use AI_ADDRESS_MASKING=map"
                    )


def is_meaning_only(address: Address) -> bool:
    """Netmask / wildcard shapes and 0.0.0.0: they identify nothing, so they are not masked."""
    if address.version != 4:
        return False
    value = int(address)
    if value >= 0xFF000000:  # 255.x.x.x: a netmask has its zero bits at the end
        inverted = ~value & 0xFFFFFFFF
        return inverted & (inverted + 1) == 0
    if value <= 0x00FFFFFF:  # 0.x.x.x: a wildcard mask has its one bits at the end
        return value & (value + 1) == 0
    return False


def _block_of(address: Address) -> Network:
    size = AUTO_BLOCK_V4 if address.version == 4 else AUTO_BLOCK_V6
    return ipaddress.ip_network(f"{address.compressed.partition('%')[0]}/{size}", strict=False)


def _plain(address: Address) -> Address:
    """The address without an IPv6 zone id (``fe80::1%eth0`` -> ``fe80::1``)."""
    if address.version == 6 and getattr(address, "scope_id", None):
        return ipaddress.IPv6Address(int(address))
    return address


class AddressMasker:
    """The masking state of one request. Not shared between requests or threads."""

    def __init__(self, address_map: AddressMap | None, *, auto: bool) -> None:
        self._map = address_map
        self._auto = auto
        # real block -> fake block handed out so far (automatic mode).
        self._real_to_fake: dict[Network, Network] = {}
        self._next_block = {4: 0, 6: 0}
        # The real blocks that occur in the request: the automatic mode never hands out a pool
        # block that holds a real address of the request, so a pseudonym is never a real address.
        self._seen_blocks: set[Network] = set()
        # fake address -> real address, for every fake the masker produced. This is all that
        # ``restore`` ever puts back: an address the model was never shown stays as it is.
        self._emitted: dict[Address, Address] = {}

    @property
    def masked_count(self) -> int:
        """Distinct addresses replaced by a fake one so far (never the addresses themselves)."""
        return len(self._emitted)

    def observe(self, addresses: Iterable[Address]) -> None:
        """Note the real addresses of the text about to be masked (before any is replaced)."""
        for address in addresses:
            plain = _plain(address)
            if plain.version == 6 and plain.ipv4_mapped is not None:  # type: ignore[union-attr]
                plain = plain.ipv4_mapped  # type: ignore[union-attr]
            self._seen_blocks.add(_block_of(plain))

    def mask(self, literal: str) -> str | None:
        """The text to send instead of ``literal``; ``None`` means the caller must tokenise it."""
        try:
            address = _plain(ipaddress.ip_address(literal))
        except ValueError:
            return None
        if is_meaning_only(address):
            return literal
        if address in self._emitted:
            # A real address that equals a fake handed out earlier: restoring it would be ambiguous.
            return None
        mapped = address.ipv4_mapped if address.version == 6 else None  # type: ignore[union-attr]
        if mapped is not None:  # ::ffff:a.b.c.d is the IPv4 host a.b.c.d
            if is_meaning_only(mapped):
                return literal
            inner = self._fake_of(mapped)
            if inner is None:
                return None
            text = f"::ffff:{inner}"
            self._emitted[ipaddress.IPv6Address(text)] = address
            return text
        fake = self._fake_of(address)
        if fake is None:
            return None
        self._emitted[fake] = address
        return str(fake)

    def _fake_of(self, address: Address) -> Address | None:
        fake = self._map.to_fake(address) if self._map is not None else None
        if fake is None and self._auto:
            fake = self._auto_fake(address)
        # A stand-in that equals the real address is no masking at all.
        return None if fake is None or fake == address else fake

    def _auto_fake(self, address: Address) -> Address | None:
        block = _block_of(address)
        fake_block = self._real_to_fake.get(block)
        if fake_block is None:
            fake_block = self._allocate(block)
            if fake_block is None:
                return None
            self._real_to_fake[block] = fake_block
        return type(address)(_start(fake_block) + int(address) - _start(block))

    def _allocate(self, block: Network) -> Network | None:
        pool = AUTO_POOL_V4 if block.version == 4 else AUTO_POOL_V6
        index = self._next_block[block.version]
        while True:
            base = _start(pool) + index * block.num_addresses
            if base + block.num_addresses - 1 > _end(pool):
                return None
            candidate = ipaddress.ip_network((type(block.network_address)(base), block.prefixlen))
            index += 1
            if candidate not in self._seen_blocks:  # never a block that holds a real address
                self._next_block[block.version] = index
                return candidate

    def restore(self, text: str, patterns: Iterable[re.Pattern[str]]) -> str:
        """Put the real address back for each fake one handed out in this request.

        Only those exact addresses are restored. A neighbour of a fake address, the fake prefix
        itself, a prefix length, tokens and secrets stay as they are.
        """
        if not self._emitted:
            return text

        def put_back(match: re.Match[str]) -> str:
            try:
                address = _plain(ipaddress.ip_address(match.group(0)))
            except ValueError:
                return match.group(0)
            real = self._emitted.get(address)
            if real is None:
                return match.group(0)
            if real.version == 6 and real.ipv4_mapped is not None:  # type: ignore[union-attr]
                return f"::ffff:{real.ipv4_mapped}"  # type: ignore[union-attr]
            return str(real)

        for pattern in patterns:
            text = pattern.sub(put_back, text)
        return text


def build_masker(mode: str, address_map: AddressMap | None) -> AddressMasker | None:
    """A fresh masker for one request, or ``None`` in ``tokens`` mode (today's behaviour)."""
    if mode == MODE_TOKENS:
        return None
    return AddressMasker(address_map, auto=mode == MODE_AUTO)
