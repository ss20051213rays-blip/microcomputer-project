"""pytest 全局 fixtures。"""
from typing import Any, Dict

import pytest

from pantilt.bootstrap import create_app
from pantilt.infrastructure.config import load_config
from pantilt.infrastructure.paths import DEFAULT_CONFIG


@pytest.fixture
def app_config() -> Dict[str, Any]:
    return load_config(DEFAULT_CONFIG)


@pytest.fixture
def running_app(app_config):
    app = create_app(app_config, dry_run=True)
    assert app.start(), "Failed to start running_app in fixture"
    yield app
    app.stop()

