try:
    import yaml
except ImportError:
    try:
        from ruamel.yaml import YAML
        class _YamlCompat:
            @staticmethod
            def safe_load(stream):
                y = YAML(typ='safe')
                return y.load(stream)
        yaml = _YamlCompat()
    except ImportError:
        yaml = None

import logging
import sys

def setup_logger(config):
    level_str = config.get("logging", {}).get("level", "INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger("App")

def load_config(path):
    if yaml is None:
        print("[Fatal] Neither PyYAML nor ruamel.yaml is installed.")
        sys.exit(1)
    try:
        with open(path, 'r', encoding='utf-8') as f:
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

