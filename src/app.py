import argparse
import sys
import time
from src.config import load_config, setup_logger

def main():
    parser = argparse.ArgumentParser(description="视听融合声源定位与目标跟踪云台")
    parser.add_argument("--config", default=__import__("os").path.abspath(__import__("os").path.join(__import__("os").path.dirname(__file__), "..", "configs", "default.yaml")), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="无硬件干运行模式")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logger(config)
    
    logger.info(f"Loaded config: version {config.get('config_version', 'unknown')}")
    
    if args.dry_run:
        logger.info("Starting in DRY-RUN mode. No hardware will be driven.")
        try:
            logger.info("Dry run simulation active for 30 seconds (or press Ctrl+C to stop)...")
            time.sleep(30)
            logger.info("Dry run completed successfully.")
        except KeyboardInterrupt:
            logger.info("Dry run interrupted by user.")
        sys.exit(0)

    # 阶段一留空：后续此处将初始化音视频线程和主状态机循环
    logger.info("Hardware mode placeholder: Stage 1 complete. Exiting.")

if __name__ == "__main__":
    main()

