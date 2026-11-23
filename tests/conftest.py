import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from us_stock_picks import config as cfg  # noqa: E402


@pytest.fixture(autouse=True)
def _no_default_scan_dirs(monkeypatch):
    """Never look in the real home directory for scan workbooks."""
    monkeypatch.setattr(cfg, "DEFAULT_SCAN_DIRS", [])
