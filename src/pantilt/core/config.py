"""配置文件加载与校验基础设施。"""
import sys
from pathlib import Path
from typing import Any, Dict, Union

try:
    import yaml
except ImportError:
    try:
        from ruamel.yaml import YAML

        class _YamlCompat:
            @staticmethod
            def safe_load(stream):
                y = YAML(typ="safe")
                return y.load(stream)

        yaml = _YamlCompat()
    except ImportError:
        yaml = None

from pantilt.core.logging_setup import setup_logger
from pantilt.core.paths import DEFAULT_CONFIG


def load_config(path: Union[str, Path] = DEFAULT_CONFIG) -> Dict[str, Any]:
    """加载并解析 YAML 配置文件，进行必要配置段完整性校验。"""
    if yaml is None:
        print("[Fatal] Neither PyYAML nor ruamel.yaml is installed.")
        sys.exit(1)

    path_obj = Path(path)
    try:
        with open(path_obj, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"[Fatal] Failed to load config {path}: {e}")
        sys.exit(1)

    # 简单校验必要模块配置段
    required_sections = ["audio", "camera", "servo", "control"]
    for sec in required_sections:
        if sec not in config:
            print(f"[Fatal] Config error: missing section '{sec}' in {path}")
            sys.exit(1)

    return config


__all__ = ["load_config", "setup_logger"]
