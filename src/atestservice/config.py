"""服务端配置读取。"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ServerSettings:
    """ATestService 运行配置。"""

    host: str = "127.0.0.1"
    port: int = 9091
    auth_token: str = ""
    run_repository: str = "sqlite"
    sqlite_db_path: str = "data/atestservice.db"


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.ini"


def load_settings(config_path: str | Path | None = None) -> ServerSettings:
    """从 config.ini 读取配置。"""

    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(str(path), encoding="utf-8-sig")

    return ServerSettings(
        host=cfg.get("server", "host", fallback="127.0.0.1"),
        port=cfg.getint("server", "port", fallback=9091),
        auth_token=cfg.get("auth", "token", fallback=""),
        run_repository=cfg.get("runs", "repository", fallback="sqlite"),
        sqlite_db_path=cfg.get("runs", "sqlite_db_path", fallback="data/atestservice.db"),
    )
