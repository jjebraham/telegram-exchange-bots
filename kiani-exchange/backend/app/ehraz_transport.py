"""HTTPS to Ehraz through an opaque SSH byte stream on loopback.

The original hostname is retained for certificate verification and TLS SNI.
Authorization and identity data remain inside Google-to-Ehraz TLS.
"""
import asyncio
import json
import socket
import ssl

import aiohttp

ALLOWED_PATHS = frozenset({
    "/api/v1/match/national-with-mobile",
    "/api/v1/match/card-with-national",
    "/api/v1/info/identity-similarity",
})


class EhrazLoopbackResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host != "ehraz.io" or port != 443:
            raise OSError("unexpected_ehraz_destination")
        return [{"hostname": host, "host": "127.0.0.1", "port": 18443,
                 "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self):
        pass


async def tunnel_json(method, path, token, payload=None, timeout_seconds=12):
    if path not in ALLOWED_PATHS and not (
        method == "GET" and path == "/api/v1/account/wallet-balance"
    ):
        raise ValueError("unexpected_ehraz_path")
    for attempt in range(2):
        connector = aiohttp.TCPConnector(
            resolver=EhrazLoopbackResolver(),
            ssl=ssl.create_default_context(), use_dns_cache=False,
        )
        timeout = aiohttp.ClientTimeout(
            total=max(6, min(timeout_seconds, 15)), sock_connect=5,
        )
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.request(
                    method, "https://ehraz.io" + path, json=payload,
                    headers={"Authorization": "Token " + token,
                             "Accept": "application/json"}, allow_redirects=False,
                ) as response:
                    body = await response.content.read(65537)
                    if len(body) > 65536:
                        return response.status, {}
                    try:
                        data = json.loads(body)
                    except (ValueError, UnicodeDecodeError):
                        data = {}
                    return response.status, data if isinstance(data, dict) else {}
        except aiohttp.ClientConnectorCertificateError:
            raise
        except aiohttp.ClientConnectorSSLError:
            raise
        except aiohttp.ClientConnectorError:
            # Connection/TLS setup failed before an HTTP request was sent.
            # Never repeat a sent POST after an ambiguous timeout/response.
            if attempt:
                raise
            await asyncio.sleep(0.2)
