"""Proxy support of the AI provider adapters, against a real local fake proxy."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable

import pytest

from core.ssl_config import create_verified_ssl_context
from services.ai_assistant.chat_service import check_connection
from services.ai_assistant.providers.anthropic_provider import AnthropicProvider
from services.ai_assistant.providers.base import ChatMessage, ProviderUnavailableError
from services.ai_assistant.providers.gemini_provider import GeminiProvider
from services.ai_assistant.providers.openai_compat_provider import OpenAiCompatProvider
from services.ai_assistant.providers.proxy import (
    BypassEntryError,
    ProxyConfig,
    httpx_client_options,
    is_bypassed,
    parse_bypass_entry,
)
from services.ai_assistant.settings_service import AiRuntimeConfig

HISTORY = [ChatMessage(role="user", content="hi")]
EXPECTED_AUTH = "Basic " + base64.b64encode(b"proxyuser:p@ss:word").decode()
SSE_BODY = (
    b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
)


class FakeProxy:
    """Records each request head; answers with ``respond(head)`` (raw bytes)."""

    def __init__(self, respond: Callable[[str], bytes]) -> None:
        self.heads: list[str] = []
        self._respond = respond
        self._server: asyncio.Server | None = None
        self.port = 0

    async def __aenter__(self) -> FakeProxy:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
        self.heads.append(head)
        writer.write(self._respond(head))
        await writer.drain()
        writer.close()

    def header(self, name: str) -> str | None:
        for line in self.heads[-1].split("\r\n")[1:]:
            key, _, value = line.partition(":")
            if key.lower() == name.lower():
                return value.strip()
        return None


def _reply_407(_: str) -> bytes:
    return b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n"


def _reply_sse(_: str) -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
        + SSE_BODY
    )


def _config(proxy: FakeProxy, **kwargs: object) -> ProxyConfig:
    return ProxyConfig(url=proxy.url, username="proxyuser", password="p@ss:word", **kwargs)  # type: ignore[arg-type]


async def _drain(provider: object) -> None:
    async for _ in provider.stream(  # type: ignore[attr-defined]
        model="m1", system="s", messages=list(HISTORY), max_tokens=10
    ):
        pass


def _run(scenario: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(scenario())


def test_openai_compat_sends_request_through_proxy_with_basic_auth() -> None:
    async def scenario() -> None:
        async with FakeProxy(_reply_sse) as proxy:
            provider = OpenAiCompatProvider("http://10.0.0.5:11434/v1", proxy=_config(proxy))
            try:
                await _drain(provider)
            finally:
                await provider.aclose()
        assert proxy.heads[0].startswith("POST http://10.0.0.5:11434/v1/chat/completions")
        assert proxy.header("Proxy-Authorization") == EXPECTED_AUTH

    _run(scenario)


def test_gemini_connect_carries_proxy_credentials_and_407_is_neutral() -> None:
    async def scenario() -> None:
        async with FakeProxy(_reply_407) as proxy:
            provider = GeminiProvider("AIza-key", proxy=_config(proxy))
            try:
                with pytest.raises(ProviderUnavailableError) as caught:
                    await _drain(provider)
            finally:
                await provider.aclose()
        assert proxy.heads[0].startswith("CONNECT generativelanguage.googleapis.com:443")
        assert proxy.header("Proxy-Authorization") == EXPECTED_AUTH
        assert "p@ss" not in str(caught.value) and proxy.url not in str(caught.value)

    _run(scenario)


def test_anthropic_connect_goes_through_proxy() -> None:
    async def scenario() -> None:
        async with FakeProxy(_reply_407) as proxy:
            provider = AnthropicProvider("sk-ant-test", proxy=_config(proxy))
            try:
                with pytest.raises(ProviderUnavailableError):
                    await _drain(provider)
            finally:
                await provider.aclose()
        assert proxy.heads[0].startswith("CONNECT api.anthropic.com:443")
        assert proxy.header("Proxy-Authorization") == EXPECTED_AUTH

    _run(scenario)


def test_bypassed_host_connects_directly() -> None:
    async def scenario() -> None:
        async with FakeProxy(_reply_407) as proxy:
            provider = OpenAiCompatProvider(
                "http://127.0.0.1:9/v1", proxy=_config(proxy, bypass_hosts=("127.0.0.1",))
            )
            try:
                with pytest.raises(ProviderUnavailableError):
                    await _drain(provider)  # nothing listens on :9
            finally:
                await provider.aclose()
        assert proxy.heads == []

    _run(scenario)


def test_proxy_without_username_sends_no_auth() -> None:
    async def scenario() -> None:
        async with FakeProxy(_reply_sse) as proxy:
            provider = OpenAiCompatProvider(
                "http://10.0.0.5:11434/v1", proxy=ProxyConfig(url=proxy.url)
            )
            try:
                await _drain(provider)
            finally:
                await provider.aclose()
        assert proxy.header("Proxy-Authorization") is None

    _run(scenario)


def test_without_proxy_only_tls_context_is_set_so_env_proxies_keep_working() -> None:
    options = httpx_client_options(None, "https://example.com")
    assert set(options) == {"verify"}
    assert options["verify"] is create_verified_ssl_context()


def test_tls_context_trusts_os_store_and_covers_proxy_and_bypass() -> None:
    context = create_verified_ssl_context()
    proxy = ProxyConfig(url="https://proxy:3128", bypass_hosts=("lan.corp",))
    assert httpx_client_options(proxy, "https://api.example.com")["verify"] is context
    assert httpx_client_options(proxy, "http://lan.corp/v1")["verify"] is context


def test_configured_proxy_ignores_environment() -> None:
    options = httpx_client_options(ProxyConfig(url="http://proxy:3128"), "https://example.com")
    assert options["trust_env"] is False
    assert "proxy" in options


@pytest.mark.parametrize(
    ("entries", "target", "expected"),
    [
        (("ollama.corp",), "http://ollama.corp:11434/v1", True),
        (("corp.example",), "http://ollama.corp.example/v1", True),
        ((".corp.example",), "http://ollama.corp.example/v1", True),
        (("*.corp.example",), "http://ollama.corp.example/v1", True),
        (("corp.example",), "http://notcorp.example/v1", False),
        (("ollama",), "http://ollama/v1", True),
        (("ollama",), "http://ollama.corp/v1", False),  # single label = exact name only
        (("ollama.corp",), "http://OLLAMA.corp./v1", True),  # case and trailing dot
        (("corp.example",), "http://ollama.corp.example./v1", True),
        (("10.0.0.0/8",), "http://10.1.2.3/v1", True),
        (("10.0.0.0/8",), "http://192.168.1.1/v1", False),
        (("10.0.0.0/8",), "http://[::1]/v1", False),  # other family
        (("10.1.2.3",), "http://10.1.2.3/v1", True),
        (("10.1.2.3",), "http://10.1.2.30/v1", False),
        (("fd00::/8",), "http://[fd00::5]/v1", True),
        ((), "http://ollama.corp/v1", False),
        # A name entry never matches an IP literal, and a one-label entry never matches a suffix.
        (("com",), "https://api.anthropic.com", False),
        (("com",), "https://generativelanguage.googleapis.com", False),
        # Entries that do not parse stay on the proxy instead of exempting something else.
        (("1",), "http://10.0.0.1", False),
        (("8",), "http://8.8.8.8", False),
        (("2.3",), "http://10.1.2.3", False),
        (("10.0.0",), "http://10.0.0.5", False),
        (("0.0.0.0/0",), "http://8.8.8.8", False),
    ],
)
def test_bypass_matching(entries: tuple[str, ...], target: str, expected: bool) -> None:
    assert is_bypassed(ProxyConfig(url="http://p:1", bypass_hosts=entries), target) is expected


@pytest.mark.parametrize(
    "entry",
    [
        "1",
        "8",
        "*.8",
        "2.3",
        "10.0.0",
        "*.com",
        ".com",
        "0.0.0.0/0",
        "::/0",
        "a b",
        "-x.corp",
        "10.0.0.0/33",
        "*",
        "",
    ],
)
def test_unsafe_or_ambiguous_bypass_entries_are_refused(entry: str) -> None:
    with pytest.raises(BypassEntryError):
        parse_bypass_entry(entry)


def test_password_not_in_repr() -> None:
    assert "secret-pw" not in repr(
        ProxyConfig(url="http://p:1", username="u", password="secret-pw")
    )


def test_error_for_status_407_is_neutral() -> None:
    from services.ai_assistant.providers.http_common import error_for_status

    err = error_for_status(407, "<html>proxy says secret</html>")
    assert isinstance(err, ProviderUnavailableError)
    assert "secret" not in str(err) and "407" in str(err)


def _config_with_proxy(url: str = "http://10.1.1.1:3128") -> AiRuntimeConfig:
    return AiRuntimeConfig(
        provider="anthropic",
        model="m",
        base_url=None,
        api_key="k",
        share_inventory_data=False,
        share_content_data=False,
        proxy=ProxyConfig(url=url, username="u", password="pw"),
    )


class _Recorder:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def __call__(self, **kwargs: object) -> object:
        self.kwargs = kwargs

        class _Provider:
            async def stream(self, **_: object):
                if False:
                    yield None

        return _Provider()


def test_check_connection_hands_proxy_to_provider_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow(url: str) -> str:
        return url

    monkeypatch.setattr("services.ai_assistant.chat_service.validate_proxy_url_async", allow)
    factory = _Recorder()

    result = asyncio.run(check_connection(_config_with_proxy(), provider_factory=factory))

    assert result["ok"] is True
    assert factory.kwargs["proxy"] == _config_with_proxy().proxy


def test_no_proxy_keeps_factory_signature_unchanged() -> None:
    factory = _Recorder()
    config = AiRuntimeConfig(
        provider="anthropic",
        model="m",
        base_url=None,
        api_key="k",
        share_inventory_data=False,
        share_content_data=False,
    )

    asyncio.run(check_connection(config, provider_factory=factory))

    assert "proxy" not in factory.kwargs


def test_unsafe_saved_proxy_url_is_refused_before_any_call() -> None:
    factory = _Recorder()

    result = asyncio.run(
        check_connection(
            _config_with_proxy("http://169.254.169.254:3128"), provider_factory=factory
        )
    )

    assert result["ok"] is False
    assert factory.kwargs == {}


# -- private CA: the providers must trust the same store as the other sources ---------------


def _make_private_ca_and_server_cert(directory):  # noqa: ANN001, ANN202
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.UTC)

    def name(cn: str) -> x509.Name:
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(name("Test Corp Root CA"))
        .issuer_name(name("Test Corp Root CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name("llm.corp.test"))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_pem = directory / "ca.pem"
    ca_pem.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "server.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_pem, directory / "server.pem", directory / "server.key"


def test_https_server_with_private_ca_works_only_when_ca_is_trusted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ssl

    ca_pem, cert, key = _make_private_ca_and_server_cert(tmp_path)

    # Loopback is blocked by the outbound-URL policy; this test is about TLS only.
    async def allow(url: str, **_: object) -> str:
        return url

    monkeypatch.setattr(
        "services.ai_assistant.providers.openai_compat_provider.validate_llm_base_url_async", allow
    )

    async def serve(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _.readuntil(b"\r\n\r\n")
        writer.write(_reply_sse(""))
        await writer.drain()
        writer.close()

    async def scenario(trusted: bool) -> None:
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert, key)
        server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=server_ctx)
        port = server.sockets[0].getsockname()[1]
        provider = OpenAiCompatProvider(f"https://127.0.0.1:{port}/v1")
        try:
            if trusted:
                await _drain(provider)
            else:
                with pytest.raises(ProviderUnavailableError):
                    await _drain(provider)
        finally:
            await provider.aclose()
            server.close()
            await server.wait_closed()

    # Default trust (what a fresh container without the company CA has): refused.
    asyncio.run(scenario(trusted=False))

    # The company CA installed in the trust store: accepted.
    context = ssl.create_default_context(cafile=str(ca_pem))
    monkeypatch.setattr(
        "services.ai_assistant.providers.proxy.create_verified_ssl_context", lambda: context
    )
    asyncio.run(scenario(trusted=True))
