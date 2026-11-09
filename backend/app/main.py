"""FastAPI app: /health, /api routers, and frontend/dist with SPA fallback (SPEC 5)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlmodel import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .api import deps, reference, runs
from .api.deps import ApiError
from .config import settings
from .seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    deps.reset_run_lock()
    engine = db.init_engine(settings.db_path)
    with Session(engine) as s:
        seed_if_empty(s, settings.data_dir)
    log.info("DB %s, data %s, model %s", settings.db_path, settings.data_dir, settings.extraction.model)
    yield


app = FastAPI(title="Invoice processing pipeline", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(_req: Request, exc: ApiError):
    return _err(exc.status, exc.code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_req: Request, exc: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _err(exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(_req: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    return _err(422, "validation_error", f"{loc}: {first.get('msg', 'invalid request')}")


@app.get("/health")
@app.get("/api/health", include_in_schema=False)
def health():
    try:
        with Session(db.get_engine()) as s:
            s.exec(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        db_status = f"error: {exc}"
    return {"ok": db_status == "ok", "model": settings.extraction.model, "db": db_status}


app.include_router(runs.router)
app.include_router(reference.router)


# ---- frontend (built SPA) ------------------------------------------------------------------
@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        return _err(404, "not_found", f"No API route /{full_path}.")
    dist: Path = settings.frontend_dist
    index = dist / "index.html"
    if not index.exists():
        return _err(404, "frontend_not_built", "frontend/dist is not built; the API is under /api.")
    candidate = (dist / full_path).resolve()
    if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index)
