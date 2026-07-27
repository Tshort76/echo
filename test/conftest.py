from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DATA = REPO_ROOT / "resources" / "demo_data"


@pytest.fixture(scope="session")
def demo_data() -> Path:
    """Path to the bundled sample documents.

    Anchored on ``__file__`` rather than the cwd, so ``pytest`` works from the
    repo root as well as from inside ``test/``.
    """
    if not DEMO_DATA.is_dir():
        pytest.skip(f"demo data not available at {DEMO_DATA}")
    return DEMO_DATA
