"""Loopback-only TLS transport. No API credentials or plaintext HTTP here."""
import asyncio
import contextlib
import logging

SSH = (
    "/usr/bin/ssh", "-T",
    "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=/home/kianirad2020/.ssh/kiani_akamai_rates_known_hosts",
    "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2", "-o", "ClearAllForwardings=yes",
    "-i", "/home/kianirad2020/.ssh/shahidi_ehraz_tls_ed25519",
    "shahidi-ehraz@139.162.186.28",
)
active_connections = 0


async def pump(reader, writer):
    total = 0
    while block := await reader.read(65536):
        total += len(block)
        if total > 2 * 1024 * 1024:
            raise ValueError("stream_limit")
        writer.write(block)
        await writer.drain()


async def handle(reader, writer):
    global active_connections
    if active_connections >= 16:
        writer.close()
        await writer.wait_closed()
        return
    active_connections += 1
    process = None
    tasks = []
    try:
        process = await asyncio.create_subprocess_exec(
            *SSH, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        tasks = [asyncio.create_task(pump(reader, process.stdin)),
                 asyncio.create_task(pump(process.stdout, writer))]
        done, _ = await asyncio.wait(tasks, timeout=35,
                                     return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (OSError, ValueError, asyncio.TimeoutError, ConnectionError) as error:
        logging.warning("TLS transport closed: %s", type(error).__name__)
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        active_connections -= 1


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", 18443, limit=65536)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
