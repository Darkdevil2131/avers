"""Run: python -m noesis.mcp_server [--transport stdio|http] [--port 8765]
Env: NOESIS_URL (default http://localhost:8000), NOESIS_TOKEN or NOESIS_API_KEY."""
import argparse
import sys

from .server import create_server


def main():
    ap = argparse.ArgumentParser(prog="noesis_mcp")
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    srv = create_server()
    if a.transport == "stdio":
        srv.run()                                   # stdio: never print to stdout (it is the protocol channel)
    else:
        print(f"Serving MCP over streamable HTTP on port {a.port}", file=sys.stderr)
        import anyio
        srv.settings.port = a.port
        anyio.run(srv.run_streamable_http_async)


if __name__ == "__main__":
    main()
