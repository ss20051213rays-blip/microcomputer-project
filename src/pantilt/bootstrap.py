"""应用装配根 (Composition Root / Bootstrap)。

负责根据配置装配底层感知、执行、控制与状态机组件，构造完整的 PanTiltTrackerApp 实例。
"""
from typing import Any, Dict

from pantilt.application.tracker import PanTiltTrackerApp


def create_app(config: Dict[str, Any], dry_run: bool = False) -> PanTiltTrackerApp:
    """根据配置构建并组装云台跟踪应用实例。"""
    return PanTiltTrackerApp(config=config, dry_run=dry_run)


__all__ = ["create_app"]
