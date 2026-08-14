"""Codebase agent entrypoint.

Run on any machine you want Obrenna to have codebase access to, pointed at
the SAME address you already use to reach Obrenna:

    python -m codebase_agent.main --server https://your-obrenna-host --token <secret>
    python -m codebase_agent.main --server http://192.168.1.50:8000   (same LAN)
    python -m codebase_agent.main --server http://localhost:8000      (local dev)

The agent dials OUT to Obrenna and holds the connection open -- there is
nothing to expose and no port to forward on THIS machine. A human approves
this device by name from Obrenna's Settings once it connects.

--token is needed only when reaching Obrenna through the public gateway
(the Cloudflare tunnel). Every route behind that gateway normally requires a
browser login cookie, which a headless agent cannot obtain; the token is what
gets this one route through instead. Connecting directly to the backend --
localhost or over your own LAN -- needs no token, because the gateway isn't in
the path.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

from . import ws_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Obrenna Codebase Agent")
    parser.add_argument("--server", required=True, help="Obrenna's address, e.g. https://your-obrenna-host")
    parser.add_argument("--name", default=None, help="Friendly name shown in Obrenna's approval list (defaults to this machine's hostname)")
    parser.add_argument(
        "--token",
        default=None,
        help=(
            "Shared secret for reaching Obrenna through the public gateway. "
            "Defaults to $OBRENNA_AGENT_TOKEN. Not needed when connecting "
            "directly to the backend (localhost or LAN)."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    # Env var is the better habit for a secret: a --token on the command line
    # is visible in the process list and shell history to anyone on the box.
    token = args.token or os.getenv("OBRENNA_AGENT_TOKEN") or ""

    try:
        asyncio.run(ws_client.run(args.server, args.name, token=token))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
