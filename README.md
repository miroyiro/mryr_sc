# mryr_sc — 미로이로 스크랩 서버

외부 소스(API·RSS·스크래핑)에서 공연/팝업/뉴스를 수집 → 가공·검수 → 승인분을 backend 내부 API로 반영합니다.
DB는 `miroyiro_scrap` 스키마만 사용합니다 (main 스키마 접근 X).

## 기술 스택
Python 3.10+ · FastAPI · SQLAlchemy(async) + asyncpg · Alembic · APScheduler · httpx · BeautifulSoup · RapidFuzz · PostgreSQL 16

## 준비물
- Python 3.10 이상
- Docker Desktop (Windows는 WSL Integration 켜기)

## 로컬 실행
```bash
# 1) 가상환경 + 라이브러리
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) 환경변수
cp .env.example .env

# 3) DB 켜기 (localhost:5433)
docker compose -f docker-compose.dev.yml up -d

# 4) 테이블 생성
alembic upgrade head

# 5) 서버 실행
uvicorn src.main:app --reload
```
- 확인: http://localhost:8000/health → `{"status":"ok"}`
- API 문서: http://localhost:8000/docs
- DB 접속(DBeaver 등): `localhost:5433` / DB `miroyiro` / `dev` / `dev`

## 마이그레이션 (Alembic)
```bash
alembic revision --autogenerate -m "설명"   # 모델 변경 → 마이그레이션 파일 생성
alembic upgrade head                         # 적용
alembic downgrade -1                         # 한 단계 되돌리기
```
- **revision은 한 사람씩, 순서대로** 만들기. 머지 전 `alembic heads`가 1개인지 확인
- autogenerate는 `miroyiro_scrap` 스키마만 비교함 (`migrations/env.py`)

## 협업 규칙
- 커밋/PR에 Jira 키 포함: `feat: 애니메이트 컬렉터 (MIRO-12)`
- 공유 파일은 작게 자주 PR: `src/main.py`(라우터 **한 줄씩** 추가), `src/config/*`, `scheduler/`, `migrations/`
- `.env`는 절대 커밋 금지 (키 추가 시 `.env.example`에 이름만 추가)
- 수집 규칙: robots.txt 준수, 소스별 간격(`scrape_source.config.delay_ms`), 본문 저장 금지 소스는 `content = NULL`
