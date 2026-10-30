"""日志基础设施配置。"""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from pantilt.infrastructure.paths import LOG_DIR, resolve_path


def setup_logger(config: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """初始化全局日志配置并返回统一主 Logger。"""
    cfg_log = (config or {}).get("logging", {})
    level_str = cfg_log.get("level", "INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)

    handlers = [logging.StreamHandler()]

    if cfg_log.get("log_to_file", False):
        log_dir_raw = cfg_log.get("log_dir", "logs")
        target_dir = resolve_path(log_dir_raw)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(target_dir / "app.log", encoding="utf-8")
            handlers.append(file_handler)
        except Exception as e:
            print(f"[Warn] Failed to initialize file logger at {target_dir}: {e}")

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("App")


__all__ = ["setup_logger"]
