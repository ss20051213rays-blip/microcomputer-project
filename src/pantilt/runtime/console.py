"""终端交互监听线程。"""
import logging
import sys
import threading
from typing import Callable, Optional

logger = logging.getLogger("App")


class ConsoleListener:
    """
    终端按键监听器（守护线程）。
    支持按键命令：
    - 'c': 强制复位回中
    - 'q': 安全退出
    """

    def __init__(
        self,
        on_center: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ):
        self.on_center = on_center
        self.on_quit = on_quit
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """如果处于交互终端环境，启动后台监听线程。"""
        if not sys.stdin.isatty():
            return False

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("控制台交互已就绪：输入 'c' 强制回中并重置，输入 'q' 安全退出。")
        return True

    def stop(self):
        """停止控制台监听。"""
        self.running = False

    def _run_loop(self):
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if cmd == "c":
                    logger.info("[指令] 收到终端回中指令 'c'，复位云台至 IDLE。")
                    if self.on_center:
                        self.on_center()
                elif cmd == "q":
                    logger.info("[指令] 收到终端退出指令 'q'。")
                    if self.on_quit:
                        self.on_quit()
                    break
            except Exception:
                break


__all__ = ["ConsoleListener"]

