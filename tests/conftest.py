"""Keep pytest scratch space inside this workspace on restricted Windows hosts."""
from pathlib import Path
import tempfile


def pytest_configure(config):
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1] / "outputs" / "pytest-tmp"
        root.mkdir(parents=True, exist_ok=True)
        # Unique, initially empty directory; never asks pytest to clear user data.
        config.option.basetemp = tempfile.mkdtemp(prefix="run-", dir=root)
