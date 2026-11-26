# miroyiro-scrap 배포 이미지 (미니PC). 실행은 docker-compose.yml 참고.
# Chromium(playwright install) 은 넣지 않는다 → PLAYWRIGHT_ENABLED=false 고정.
FROM python:3.12-slim

ENV TZ=Asia/Seoul \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_ENABLED=false

# slim 에는 tzdata 가 없어서 TZ 가 안 먹음
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 (코드만 바뀌면 이 레이어는 캐시 재사용)
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app src ./src
# 관리 GUI 계정 CLI 한 파일만 (scripts/ 의 나머지는 외부 사이트를 긁는 개발용이라 제외).
# __init__.py 없이도 python -m scripts.create_admin 동작 (namespace package, WORKDIR=/app)
COPY --chown=app:app scripts/create_admin.py ./scripts/create_admin.py

USER app

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
