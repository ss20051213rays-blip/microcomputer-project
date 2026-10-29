"""项目路径唯一来源：禁止在其它模块手写 '..' 相对路径。"""
from pathlib import Path

# src/pantilt/core/paths.py -> 上溯 4 级得到仓库根
PROJECT_ROOT = Path(__file__).resolve().parents[3]

CONFIG_DIR = PROJECT_ROOT / "configs"
DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
ASSETS_DIR = PROJECT_ROOT / "assets"
