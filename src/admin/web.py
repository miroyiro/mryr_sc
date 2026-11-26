"""관리 GUI 화면 서빙 + /admin 보안 헤더 + 500 응답 고정. main.py 에서 install(app) 한 번.

- GET /admin          → static/index.html (데이터 없는 껍데기. 데이터는 JS 가 /admin/api 로 받음)
- /admin/static/*     → css·js
- /admin/** 의 처리 안 된 예외 → 고정 JSON (예외 메시지·stack·경로를 응답에 안 넣음. 로그에는 남음)
- 그 외 경로 500 은 지금과 똑같이 'Internal Server Error' 텍스트 (/internal 동작 불변)
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("miroyiro-scrap.admin")

ADMIN_500 = {"error": "internal_error", "detail": "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요"}

SECURITY_HEADERS = {
    # 같은 출처 파일만 실행·로드 → 인라인 스크립트·외부 스크립트 주입(XSS) 차단
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",                  # 다른 사이트 iframe 에 넣어 클릭 유도 방지
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def install(app: FastAPI) -> None:
    @app.get("/admin", include_in_schema=False)
    async def admin_page():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/admin/static", StaticFiles(directory=STATIC_DIR), name="admin-static")

    @app.middleware("http")
    async def admin_headers(request: Request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path == "/admin" or path.startswith("/admin/"):
            resp.headers.update(SECURITY_HEADERS)
            if path.startswith("/admin/api/"):
                resp.headers["Cache-Control"] = "no-store"   # 로그인 응답이 브라우저·프록시 캐시에 안 남게
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)   # 원인은 서버 로그에만
        if request.url.path.startswith("/admin"):
            return JSONResponse(status_code=500, content=ADMIN_500)
        return PlainTextResponse("Internal Server Error", status_code=500)   # Starlette 기본과 동일
