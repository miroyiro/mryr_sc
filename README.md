# 🎤 MIROYIRO · 수집 서버
“좋아하는 마음에는 끝이 없으니까!”
> **J-POP·애니메이션 일정과 소식을 모아 가공하는 MIROYIRO의 수집 서버**

---

## 💡 프로젝트 개요 (Overview)
**MIROYIRO(미로이로)** 는 대한민국에서 일본 대중문화(J-POP, 애니메이션 등)에 대한 관심을 한곳에서 해소할 수 있는 온라인 플랫폼입니다.
*J-POP과 애니메이션 덕질을, 한곳에서. — 덕질하기 좋은 날.* ([홍보 인스타그램](https://www.instagram.com/miro_yiro/))

이 저장소는 그중 **정보를 가장 빠르고 정확하게** 모아 오는 수집 서버입니다.
공연·방영·뉴스·시청 플랫폼 정보를 외부 API와 사이트에서 수집해 가공하고, 메인 서버(`mryr_be`)로 넘깁니다. 운영자가 수집 상태를 확인하는 관리 화면도 함께 들어 있습니다.

- 수집 서버(이 저장소): Python / FastAPI / PostgreSQL
- 메인 서버: [mryr_be](https://github.com/miroyiro/mryr_be) (Spring Boot)
- 프런트엔드: [mryr_fe](https://github.com/miroyiro/mryr_fe) (React)
- 구현: Claude Code

---

## 🌟 주요 기능 및 핵심 로직 (Key Features)

| 기능 | 로직 | 기술적 특징 |
|------|------|--------------|
| 다중 소스 수집 | 내한 공연(KOPIS), 국내 방영 편성(애니시아), 시청 가능 플랫폼(TMDB), 공식 계정 소식(X), 작품 메타(AniList), 스크래핑 3곳(애니메이트·애니플러스·라프텔) | 소스마다 수집기 하나, `cls(source)` · `collect(target, params)` · `aclose()` 규약을 registry가 이름으로 선택 |
| 수집 방식 판단 | robots.txt → 페이지 구조 → 약관(저장 범위) 순으로 확인 | 공식 API > sitemap/RSS > 서버 렌더링 HTML > SPA(Playwright) 순으로 선택 |
| 작품명 매칭 | 수집한 제목을 카탈로그 작품에 연결, 임계값 미만은 붙이지 않음 | RapidFuzz, 한·일·영 표기 정규화 |
| 자동 게시 판단 | 필수값·매칭·조건을 확인해 게시 또는 보류, 보류 사유를 로그로 남김 | `can_auto_publish`를 DB 없는 순수 함수로 분리해 단위 테스트 |
| 재시도 · 멱등 | 연결 오류·5xx·429만 재시도(`Retry-After` 존중), 4xx는 재시도 안 함 | 건별 SAVEPOINT로 한 건 실패가 잡 전체를 롤백하지 않음, `processed_item_id`가 멱등키 |
| X 비용 방어 | 월 예산이 설정되지 않으면 요청 0건, 검증된 대상만 수집 | fail-closed(`XBudgetNotSet`), 실행당 읽기 건수 상한 |
| 관리 화면 | 대시보드, 소스·대상 목록, 대상 메모, X 대상 검증 | 세션 + CSRF + 역할(`editor`/`admin`), 공개 응답은 화이트리스트 스키마만 |
| 내부 API 보안 | 서버 간 호출은 `X-Internal-Key`(방향별 키 2개) | 키가 비면 전부 거부, 상수시간 비교, 비밀값은 `SecretStr` |
| 스케줄러 | APScheduler가 소스별 주기로 수집 잡 실행 | 프로세스 안에서 동작, 워커 1개 |

---

## 🏗️ 아키텍처 및 기술 스택 (Architecture & Stack)

```
외부 API·사이트 → collectors → parsers → services(가공·매칭·게시 판단) → backend(내부 API)
                       ↑                                   ↓
                  APScheduler                    PostgreSQL (스키마 miroyiro_scrap)
관리 화면(/admin) ── FastAPI 정적 서빙 + /admin/api/* ── Caddy 프록시(허용 경로만 공개)
```

- **Backend**: Python 3.12, FastAPI, httpx, BeautifulSoup, uvicorn(워커 1개)
- **Scheduling**: APScheduler (프로세스 안)
- **Matching**: RapidFuzz
- **DB**: PostgreSQL 16, SQLAlchemy 2.0(async, asyncpg), Alembic
- **Scraping**: httpx + BeautifulSoup, Playwright(애니플러스 동시방영에만)
- **관리 화면**: 바닐라 HTML/CSS/JS (프레임워크·빌드 도구 없음), CSP 적용
- **Deploy**: Docker Compose + Caddy (미니 PC 배포 진행 중)
- **Test**: pytest (실제 응답 픽스처 사용)
- **Architecture Pattern**: collectors / parsers / services / repositories 분리, 테이블 1개 = 파일 1개

**쓰지 않은 것**
- Celery·Scrapy: 소스 수 대비 과함 / 이름 매칭에 LLM: RapidFuzz로 충분 / 멀티코어: I/O 바운드라 asyncio로 충분
- K8s·오토스케일링·MSA: 실사용자·부하가 없고, APScheduler가 프로세스 안에 있어 레플리카를 늘리면 같은 사이트를 중복 수집하기 때문

---

## 🚀 시작하기 (Getting Started)

### 1. 환경 설정
`.env.example`을 복사해 `.env`를 만들고 값을 채웁니다.

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
INTERNAL_KEY=            # 받는 키 (메인 서버 → 수집 서버)
BACKEND_INTERNAL_KEY=    # 보내는 키 (수집 서버 → 메인 서버), 위와 다른 값
BACKEND_INTERNAL_URL=
KOPIS_API_KEY=
TMDB_API_KEY=
X_BEARER_TOKEN=
SCRAPER_USER_AGENT=
SCHEDULER_ENABLED=false
PLAYWRIGHT_ENABLED=false
PUBLIC_READ=false        # 관리 화면 비로그인 읽기 허용 (기본 꺼짐)
COOKIE_SECURE=false
```

> `.env`는 `.gitignore`에 포함되어 있습니다. 실제 키는 절대 커밋하지 마세요.

### 2. 설치 & 테스트

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

### 3. Docker Compose로 실행

```bash
docker compose up -d --build            # 시작할 때 alembic upgrade head 실행
docker compose exec -it sc python -m scripts.create_admin <이름> --role admin
```

- 관리 화면: `http://127.0.0.1:8088/admin` (Caddy 프록시)
- 소스는 처음에 모두 꺼져 있습니다. 켠 뒤 `docker compose restart sc`로 스케줄을 다시 읽습니다.

---

## 📡 4. 핵심 API 엔드포인트
인증: 서버 간 `/internal/**`는 `X-Internal-Key`, 관리 화면 `/admin/api/**`는 세션 쿠키 + CSRF.

### 수집 · 파이프라인 — `/internal`
| 기능 | Method | URI | 응답 | 역할 |
|------|--------|------|------|------|
| 애니시아 수집 요청 | POST | `/internal/anissia/sync` | 202 | 방영 편성 수집 잡 등록 |
| KOPIS 수집 요청 | POST | `/internal/kopis/sync` | 202 | 내한 공연 수집 잡 등록 |
| 소스·대상·잡 관리 | - | `/internal/pipeline/**` | - | 소스·대상·스케줄·잡·검수 대기 항목·오류 |
| 작품 정보 조회 | - | `/internal/anilist/*` | - | AniList 조회·캐시(백엔드는 외부를 직접 호출하지 않음) |
| TMDB 수집 요청 | POST | `/internal/tmdb/sync` | 202 | **연결 진행 중** |

### 관리 화면 — `/admin`
| 기능 | Method | URI | 권한 |
|------|--------|------|------|
| 상태 확인 | GET | `/health` | - |
| 대시보드·소스·대상 조회 | GET | `/admin/api/*` | 로그인 (`PUBLIC_READ=true`이면 공개 가능한 항목만 비로그인) |
| 대상 메모 | PATCH | `/admin/api/targets/{id}/note` | editor 이상 |
| X 대상 검증 | POST | `/admin/api/targets/{id}/verify` | admin (예산 설정 필요) |

---

## 🧪 5. 검증 (실패 케이스 먼저)

코드를 쓰기 전에 **실패 케이스 목록을 먼저 정하고**, 구현한 뒤 **일부러 검사를 빼거나 버그를 넣어 테스트가 깨지는지** 확인했습니다.

**실패 케이스 예시**
`응답 구조 변경 → 해당 대상만 broken, 다른 대상은 계속 수집` / `빈 응답·필수 필드 누락` / `429·5xx 재시도, 4xx 무재시도` / `임계값 미만 매칭 안 붙임` / `키 없음·빈 문자열 → 요청 0건` / `X 예산 없음 → 요청 0건` / `검증 안 된 X 대상 거부`

**버그 주입으로 확인한 것**
- CSRF 비교 제거, 역할 검사 제거, 예산 검사 제거, 공개 읽기의 GET 제한 제거 → 각각 테스트가 깨짐
- 공개 응답 스키마에 `raw_data`를 넣어 보자 관련 테스트가 깨짐
- **TMDB v3 키가 httpx 요청 로그의 URL에 남는 문제를 발견해 수정** (`38e1ebe`)

**확인한 것**
- 자동 테스트 **212개 통과** (DB·외부 호출 없이 실행, 2026-11-27)
- 실사이트 수집 (2026-11-11): 애니메이트 5건 / 애니플러스 뉴스 6건 / 라프텔 20건, 총 31건, 제목·URL 누락 0
- KOPIS·애니시아는 공식 문서가 아닌 **실제 응답**을 픽스처로 저장해 테스트 (문서가 낡아 필드가 달랐던 경우가 있었음)
- TMDB 제공 플랫폼 id 6개를 공식 KR 목록과 실호출로 대조해 일치

---

## ⚠️ 6. 알려진 한계

- **미니 PC 배포는 진행 중**입니다(11/27~29). 배포 후 가동 시작 시각과 소스별 수집 건수를 여기에 기록할 예정입니다.
- TMDB·X는 수집기·테스트까지 구현했고, 처리 경로·스케줄 연결을 진행 중입니다. TMDB 검색·상세와 X의 실응답 필드는 아직 실호출로 대조하지 않았습니다.
- 실제 PostgreSQL에서 Alembic 0005 적용·롤백, Docker Compose 전체 기동, 프록시의 경로 우회 차단, 관리 화면의 브라우저 동작은 확인 예정입니다.
- 소스를 켜도 스케줄이 자동으로 다시 읽히지 않습니다(재시작 필요).
- 로그인 실패 잠금은 메모리에 저장되어 서버를 재시작하면 풀립니다(워커 1개 전제).
- 카탈로그가 비어 있는 초기에는 작품 매칭이 거의 실패해 방영 일정이 대부분 검수 대기(pending)로 쌓입니다.
- 운영 환경에서 기본 내부 키(`dev-internal-key`)를 거부하는 검사가 아직 없어, 반드시 새 키로 교체해야 합니다.
- CI/CD는 아직 없습니다(예정).

---

## 📌 출처 표기 · 이용 조건

> This product uses the TMDB API but is not endorsed or certified by TMDB.
> 시청 가능 플랫폼 정보 제공: JustWatch.

TMDB API 키는 비상업 이용 조건으로 발급되었습니다. **상업화(광고·유료·법인 명의 등) 전에는 TMDB의 승인을 받거나 TMDB 의존 기능을 꺼야 합니다.** AniList 등 다른 소스도 상업화 때 약관을 다시 확인합니다.
