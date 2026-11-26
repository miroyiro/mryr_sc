"""관리 GUI 계정 만들기 / 비밀번호 재설정 (회원가입 화면 없음 → 이 스크립트로만).

  python -m scripts.create_admin <username> --role editor
  python -m scripts.create_admin <username> --role admin --reset     # 비번·역할 바꾸고 기존 세션 전부 끊음
  (docker) docker compose exec sc python -m scripts.create_admin <username> --role admin

비밀번호는 getpass 입력창으로만 받음 (명령줄 인자 X → 셸 히스토리·ps 에 안 남음). 출력·로그에도 안 씀.
"""
import argparse
import asyncio
import getpass
import sys

from src.admin.security import MIN_PASSWORD_LEN, hash_password
from src.admin.store import AdminStore
from src.config.database import SessionLocal, engine


def ask_password() -> str:
    pw = getpass.getpass("비밀번호: ")
    if len(pw) < MIN_PASSWORD_LEN:
        sys.exit(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상")
    if getpass.getpass("비밀번호 확인: ") != pw:
        sys.exit("두 입력이 다름")
    return pw


async def main(username: str, role: str, reset: bool) -> None:
    try:
        async with SessionLocal() as db:
            store = AdminStore(db)
            user = await store.get_user_by_username(username)
            if user and not reset:
                sys.exit(f"이미 있는 계정: {username} (바꾸려면 --reset)")
            if not user and reset:
                sys.exit(f"없는 계정: {username}")
            pw_hash = hash_password(ask_password())
            if user:
                await store.update_user(user, password_hash=pw_hash, role=role)
                print(f"재설정 완료: {username} ({role}), 기존 세션 삭제")
            else:
                await store.create_user(username, pw_hash, role)
                print(f"생성 완료: {username} ({role})")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="관리 GUI 계정 생성/재설정")
    ap.add_argument("username")
    ap.add_argument("--role", choices=["editor", "admin"], required=True)
    ap.add_argument("--reset", action="store_true", help="기존 계정의 비밀번호·역할 재설정")
    a = ap.parse_args()
    asyncio.run(main(a.username.strip(), a.role, a.reset))
