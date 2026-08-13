from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Callable


class TrustedProxyHeadersMiddleware:
    """Accept forwarded scheme/client headers only from configured proxy CIDRs."""

    def __init__(self, app: Callable, trusted_proxy_cidrs: tuple[str, ...]) -> None:
        self.app = app
        self.networks = tuple(ip_network(value, strict=False) for value in trusted_proxy_cidrs)

    async def __call__(self, scope, receive, send) -> None:
        client = scope.get("client")
        if scope["type"] in {"http", "websocket"} and client and self._is_trusted(client[0]):
            headers = {key.lower(): value for key, value in scope["headers"]}
            forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode("ascii", "ignore").split(",")[0].strip()
            if forwarded_proto in {"http", "https"}:
                scope = {**scope, "scheme": forwarded_proto}
        await self.app(scope, receive, send)

    def _is_trusted(self, host: str) -> bool:
        try:
            address = ip_address(host)
            return any(address in network for network in self.networks)
        except ValueError:
            return False
