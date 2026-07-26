"""Codebase agent entrypoint.

Run on any machine you want Obrenna to have codebase access to, pointed at
the SAME address you already use to reach Obrenna:

    python -m codebase_agent.main --server https://your-obrenna-host
    python -m codebase_agent.main --server http://localhost:8000   (local dev)

The agent dials OUT to Obrenna and holds the connection open -- there is
nothing to expose, no port to forward, and no token to copy anywhere. A
human approves this device by name from Obrenna's Settings once it connects.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from . import ws_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Obrenna Codebase Agent")
    parser.add_argument("--server", required=True, help="Obrenna's address, e.g. https://your-obrenna-host")
    parser.add_argument("--name", default=None, help="Friendly name shown in Obrenna's approval list (defaults to this machine's hostname)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    try:
        asyncio.run(ws_client.run(args.server, args.name))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
