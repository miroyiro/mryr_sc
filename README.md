# mryr_sc — 미로이로 스크랩 서버

외부 소스(API·RSS·스크래핑)에서 공연/팝업/뉴스를 수집 → 가공·검수 → 승인분을 backend 내부 API로 반영합니다.
DB는 `miroyiro_scrap` 스키마만 사용합니다 (main 스키마 접근 X).

## 기술 스택
Python 3.11+ · FastAPI · SQLAlchemy(async) + asyncpg · Alembic · APScheduler · httpx · BeautifulSoup · RapidFuzz · PostgreSQL 16

## 준비물
- Python 3.11 이상 (`enum.StrEnum` 사용, 로컬 venv 는 3.12)
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

## 테스트 · 실제 데이터 확인 (DB 없이)
```bash
pip install -r requirements-dev.txt
pytest -q                                       # tests/fixtures = 2026-11-10 실제 응답 일부

# 실제 사이트를 한 번 긁어서 raw_item 모양 + 파싱 결과 출력 (저장 안 함, robots·간격 그대로)
python -m scripts.try_scrape animate --limit 3
python -m scripts.try_scrape aniplus-news
python -m scripts.try_scrape laftel --limit 5
python -m scripts.try_scrape simulcast --season fall --year 2026   # playwright install chromium 필요
```

## 마이그레이션 (Alembic)
```bash
alembic revision -m "설명"      # 빈 revision 생성 → upgrade()/downgrade() 에 SQL 직접 작성
alembic upgrade head            # 적용
alembic downgrade -1            # 한 단계 되돌리기
alembic history                 # 0001 → 0002 → 0003 ...
```
- **revision은 한 사람(명주)이 순서대로** 만들기. 머지 전 `alembic heads`가 1개인지 확인
- **`--autogenerate` 쓰지 않기**: 모델에 CHECK·인덱스를 다시 적지 않아서(진실의 원천 = 마이그레이션) autogenerate 가 인덱스를 지우는 revision 을 만듦
- CHECK 값 바꿀 때 순서: 옛 CHECK DROP → 데이터 변환 UPDATE → 새 CHECK ADD (0002 참고)

## 협업 규칙
- 작업 관리 = GitHub Projects (miroyiro org, "미로이로 개발"). 이슈 1개 = 작업 1개
- 브랜치 `feat/12-animate`, 커밋 `feat: 요약 (#12)`, PR 본문 `Closes #12` → 머지 시 이슈 닫힘·보드 카드 Done
- 공유 파일은 작게 자주 PR: `src/main.py`(라우터 **한 줄씩** 추가), `src/config/*`, `scheduler/`, `migrations/`
- `.env`는 절대 커밋 금지 (키 추가 시 `.env.example`에 이름만 추가)
- 수집 규칙: robots.txt 준수, 소스별 간격(`scrape_source.config.delay_ms`), 본문 저장 금지 소스는 `content = NULL`
