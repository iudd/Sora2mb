"""Application launcher script"""
import socket
import uvicorn
from src.core.config import config


def _get_lan_ip() -> str:
    """Best-effort LAN IP for friendly access hint."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    host = config.server_host
    port = config.server_port

    # Friendly access hints before server starts.
    if host in ("0.0.0.0", "::"):
        lan_ip = _get_lan_ip()
        print(f"👉 本机访问: http://127.0.0.1:{port}")
        if lan_ip != "127.0.0.1":
            print(f"👉 局域网访问: http://{lan_ip}:{port}")
    else:
        print(f"👉 访问: http://{host}:{port}")

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=False
    )
