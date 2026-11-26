"""(d) 배포 설정 회귀 테스트 — 파일 내용만 검사 (docker·caddy 실행 X, 네트워크 X).

실제 프록시 동작(허용 200 / 차단 404)은 배포 후 curl 로 확인. 여기서는 '누가 실수로 규칙을 넓히는 것'만 막는다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
CADDY = (ROOT / "Caddyfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    """주석(#...) 과 빈 줄 제거."""
    return [ln.split("#")[0].strip() for ln in text.splitlines() if ln.split("#")[0].strip()]


def test_caddy_allows_only_admin_and_health():
    matchers = [ln for ln in _code_lines(CADDY) if ln.startswith("@")]
    assert matchers == ["@allowed path /admin /admin/* /health"]
    proxies = [ln for ln in _code_lines(CADDY) if ln.startswith("reverse_proxy")]
    assert proxies == ["reverse_proxy sc:8000"]          # 통과 경로는 한 곳뿐
    code = "\n".join(_code_lines(CADDY))
    assert re.search(r"handle\s*\{\s*respond 404\s*\}", code)   # 나머지 전부 404
    assert "internal" not in code and "/docs" not in code
    assert "admin off" in code                             # Caddy 관리 API 끔


def test_proxy_port_is_localhost_only_and_not_8080():
    assert '"127.0.0.1:${PROXY_PORT:-8088}:8080"' in COMPOSE


def test_sc_port_binding_unchanged_and_never_all_interfaces():
    assert '"${BIND_ADDR:-127.0.0.1}:8000:8000"' in COMPOSE
    assert "0.0.0.0:" not in "\n".join(_code_lines(COMPOSE))


def test_env_example_defaults_safe():
    lines = _code_lines(ENV_EXAMPLE)
    assert "PUBLIC_READ=false" in lines
    for key in ("COOKIE_SECURE=", "SESSION_TTL_HOURS=", "PROXY_PORT="):
        assert any(ln.startswith(key) for ln in lines)
