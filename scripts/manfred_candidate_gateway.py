#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal


BUFFER_BYTES = 64 * 1024
CONNECT_TIMEOUT_SECONDS = 5.0
MAX_CONNECTIONS = 256


async def _copy_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while chunk := await reader.read(BUFFER_BYTES):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            writer.write_eof()


async def _proxy_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    *,
    upstream_host: str,
    upstream_port: int,
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(upstream_host, upstream_port),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError):
            client_writer.close()
            with contextlib.suppress(OSError):
                await client_writer.wait_closed()
            return
        try:
            client_to_upstream = asyncio.create_task(
                _copy_stream(client_reader, upstream_writer)
            )
            upstream_to_client = asyncio.create_task(
                _copy_stream(upstream_reader, client_writer)
            )
            done, pending = await asyncio.wait(
                {client_to_upstream, upstream_to_client},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
        finally:
            upstream_writer.close()
            client_writer.close()
            with contextlib.suppress(OSError):
                await upstream_writer.wait_closed()
            with contextlib.suppress(OSError):
                await client_writer.wait_closed()


async def serve_gateway(
    *,
    listen_host: str,
    listen_port: int,
    upstream_host: str,
    upstream_port: int,
    stop_event: asyncio.Event | None = None,
) -> None:
    semaphore = asyncio.Semaphore(MAX_CONNECTIONS)

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await _proxy_connection(
            reader,
            writer,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            semaphore=semaphore,
        )

    server = await asyncio.start_server(handle, listen_host, listen_port)
    async with server:
        if stop_event is None:
            await server.serve_forever()
        else:
            await stop_event.wait()


def _bounded_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixed-target TCP ingress for the egress-isolated Manfred candidate."
    )
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=_bounded_port, default=18090)
    parser.add_argument("--upstream-host", default="api")
    parser.add_argument("--upstream-port", type=_bounded_port, default=8090)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    async def run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, stop_event.set)
        await serve_gateway(
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            upstream_host=args.upstream_host,
            upstream_port=args.upstream_port,
            stop_event=stop_event,
        )

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
