"""命令行入口与运行时信号控制。"""
import argparse
import logging
import signal
import sys
from typing import List, Optional

from pantilt.application.simulation import run_simulation_test
from pantilt.bootstrap import create_app
from pantilt.infrastructure.config import load_config
from pantilt.infrastructure.logging_setup import setup_logger
from pantilt.infrastructure.paths import DEFAULT_CONFIG

logger = logging.getLogger("App")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="视听融合声源定位与目标跟踪云台主控系统")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="无硬件干运行模式")
    parser.add_argument("--simulate", action="store_true", help="执行自动化确定性模拟验收测试")
    return parser.parse_args(args)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 主入口函数。"""
    args = parse_args(argv)

    config = load_config(args.config)
    setup_logger(config)

    if args.simulate:
        success = run_simulation_test(config)
        return 0 if success else 1

    app = create_app(config, dry_run=args.dry_run)

    def sig_handler(signum, frame):
        logger.info(f"收到系统信号 {signum}，正在安全退出...")
        app.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    return app.run()


if __name__ == "__main__":
    sys.exit(main())
