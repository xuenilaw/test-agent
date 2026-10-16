"""Use the configured browser directory in both local and Linux image tests."""
import os
from pathlib import Path


def chromium_available():
    root=Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH',Path(__file__).resolve().parents[1]/'.browsers'))
    return any(path.is_file() for path in root.rglob('chrome-headless-shell'))
