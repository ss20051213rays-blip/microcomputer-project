"""项目路径唯一来源：禁止在其它模块手写 '..' 相对路径。"""
from pathlib import Path
from typing import Union

# src/pantilt/core/paths.py -> 上溯 3 级（索引 3）得到仓库根
PROJECT_ROOT = Path(__file__).resolve().parents[3]

CONFIG_DIR = PROJECT_ROOT / "configs"
DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
ASSETS_DIR = PROJECT_ROOT / "assets"


def resolve_path(path: Union[str, Path]) -> Path:
    """将相对于项目根目录的路径解析为绝对路径。"""
    p = Path(path)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


__all__ = [
    "PROJECT_ROOT",
    "CONFIG_DIR",
    "DEFAULT_CONFIG",
    "DATA_DIR",
    "LOG_DIR",
    "ASSETS_DIR",
    "resolve_path",
]
