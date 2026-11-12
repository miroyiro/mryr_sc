"""pytest 공통. DB·네트워크 없이 도는 테스트만 둔다 (fixtures/ = 2026-11-10 실제 응답 일부).

실행:  pip install -r requirements-dev.txt && pytest -q
"""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()
