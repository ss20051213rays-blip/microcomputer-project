"""pytest 全局 fixtures。"""
from typing import Any, Dict

import pytest

from pantilt.app import PanTiltTrackerApp
from pantilt.core.config import load_config
from pantilt.core.paths import DEFAULT_CONFIG


@pytest.fixture(scope="session")
def default_config() -> Dict[str, Any]:
    return load_config(DEFAULT_CONFIG)


@pytest.fixture
def dry_run_app(default_config):
    app = PanTiltTrackerApp(default_config, dry_run=True)
    assert app.start(), "Failed to start dry_run_app"
    yield app
    app.stop()

