import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from pantilt.core.config import load_config, setup_logger
from pantilt.app import run_simulation_test

def main():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "configs", "default.yaml"))
    config = load_config(config_path)
    setup_logger(config)
    success = run_simulation_test(config)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

