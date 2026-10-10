from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.is_dir():
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

from waitress import create_server  # noqa: E402

from app import create_app  # noqa: E402


def _main_server_address() -> tuple[str, int]:
    host = os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("APP_PORT", "5000"))
    except ValueError as exc:
        raise RuntimeError("APP_PORT는 1부터 65535 사이의 정수여야 합니다.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("APP_PORT는 1부터 65535 사이의 정수여야 합니다.")
    return host, port


def main():
    main_host, main_port = _main_server_address()
    if main_host not in {"127.0.0.1", "::1"}:
        raise RuntimeError("승인된 HTTPS 프록시 구성 전에는 로컬 바인딩만 허용됩니다.")
    app = create_app()  # Validate storage before logs, sockets or admin startup.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s", force=True)
    main_server = create_server(app, host=main_host, port=main_port, threads=6)
    logging.info(
        "Main app: http://%s:%s; student API blocked pending authentication integration",
        main_host,
        main_port,
    )
    main_server.run()


if __name__ == "__main__":
    main()
