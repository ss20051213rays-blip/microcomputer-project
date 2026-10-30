"""测试 bootstrap 组合根与 cli 命令行入口。"""
import pytest

from pantilt.application.tracker import PanTiltTrackerApp
from pantilt.bootstrap import create_app
from pantilt.cli import main, parse_args
from pantilt.domain.types import SystemState


def test_bootstrap_create_app(app_config):
    """验证 bootstrap.create_app 装配各层组件并注入 PanTiltTrackerApp。"""
    app = create_app(app_config, dry_run=True)
    assert isinstance(app, PanTiltTrackerApp)
    assert app.servo is not None
    assert app.audio is not None
    assert app.vision is not None
    assert app.controller is not None
    assert app.laser is not None
    assert app.state_machine is not None
    assert app.console is not None
    assert app.state == SystemState.IDLE


def test_cli_parse_args():
    """验证 CLI 命令行参数解析。"""
    args = parse_args(["--dry-run", "--simulate"])
    assert args.dry_run is True
    assert args.simulate is True

    custom_config = "configs/custom.yaml"
    args2 = parse_args(["--config", custom_config])
    assert args2.config == custom_config
    assert args2.dry_run is False


def test_cli_simulate_execution():
    """验证 CLI 执行 --simulate 模式顺利返回 0。"""
    exit_code = main(["--simulate"])
    assert exit_code == 0
