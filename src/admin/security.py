"""관리 GUI 보안 도우미: 비밀번호 해시(scrypt) · 세션/CSRF 토큰 · 로그인 시도 제한.

새 의존성 없음 (표준 라이브러리 hashlib·hmac·secrets 만).
"""
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable

# --- 비밀번호 해시 (hashlib.scrypt) ---
SCRYPT_N = 2**14   # CPU·메모리 비용. 클수록 무차별 대입이 느려짐 (1회 약 수십 ms, 메모리 = 128*N*R = 16MB)
SCRYPT_R = 8       # 블록 크기. N 과 곱해져 메모리 사용량을 정함 (표준 권장값 8)
SCRYPT_P = 1       # 병렬도. 1 = 단일 스레드 (서버 1대·workers 1 기준)
SALT_BYTES = 16    # 계정마다 다른 랜덤 salt 16바이트 → 같은 비밀번호도 해시가 다르고, 미리 계산한 표(레인보우 테이블) 무력화
DKLEN = 32         # 결과 해시 길이 32바이트
MIN_PASSWORD_LEN = 12


def hash_password(password: str) -> str:
    """'scrypt$N$r$p$salt_hex$hash_hex' 문자열. 파라미터를 같이 저장 → 나중에 N 을 올려도 기존 해시 검증 가능."""
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except ValueError:   # 형식이 깨진 해시 → 실패 (예외를 밖으로 내지 않음)
        return False
    # compare_digest: 앞 글자가 틀려도 끝까지 비교 → 응답 시간으로 해시를 한 바이트씩 맞혀보는 공격 방지
    return hmac.compare_digest(dk, expected)


# 없는 사용자로 로그인해도 scrypt 1회를 똑같이 돌림 → 응답 시간으로 '계정 존재 여부'를 알 수 없게
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# --- 세션·CSRF 토큰 ---
def new_token() -> str:
    """32바이트 랜덤 (URL 안전 문자). 세션 쿠키·CSRF 토큰 둘 다 이걸로."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """DB 에는 쿠키 원문 대신 sha256 만 저장. 토큰 자체가 고엔트로피라 salt 불필요."""
    return hashlib.sha256(token.encode()).hexdigest()


# --- 로그인 시도 제한 (메모리, 사용자명별) ---
class LoginLimiter:
    """사용자명별 연속 실패 max_fail 회 → lock_sec 동안 잠금. 성공하면 초기화.

    메모리 저장: workers=1 이라 프로세스 하나에서 일관됨. 재시작하면 초기화됨.
    한계: 남이 일부러 틀려서 관리자 계정을 잠글 수 있음 (오늘은 감수 — 보고서 참고).
    """

    def __init__(self, max_fail: int = 5, lock_sec: int = 15 * 60, clock: Callable[[], float] = time.monotonic):
        self.max_fail = max_fail
        self.lock_sec = lock_sec
        self.clock = clock
        self._fails: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, username: str) -> bool:
        until = self._locked_until.get(username)
        if until is None:
            return False
        if self.clock() >= until:          # 잠금 시간 지남 → 풀고 실패 횟수도 초기화
            self._locked_until.pop(username, None)
            self._fails.pop(username, None)
            return False
        return True

    def fail(self, username: str) -> None:
        n = self._fails.get(username, 0) + 1
        self._fails[username] = n
        if n >= self.max_fail:
            self._locked_until[username] = self.clock() + self.lock_sec

    def success(self, username: str) -> None:
        self._fails.pop(username, None)
        self._locked_until.pop(username, None)

    def reset(self) -> None:   # 테스트용
        self._fails.clear()
        self._locked_until.clear()


login_limiter = LoginLimiter()
