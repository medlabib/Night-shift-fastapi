"""Application assembly."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import auth, departments, exports, legacy, me, schedules, share

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title=settings.app_name,
    description="Fair night-shift rotas for hospital departments.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # Cookies carry the session, so credentialed requests cannot use "*".
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(departments.router)
app.include_router(departments.join_router)
app.include_router(me.router)
app.include_router(schedules.router)
app.include_router(exports.router)
app.include_router(share.router)
app.include_router(legacy.router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "version": app.version}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/s/{token}", include_in_schema=False)
def shared_view(token: str) -> FileResponse:
    """Public read-only rota. The page reads the token from its own URL."""
    return FileResponse(os.path.join(STATIC_DIR, "shared.html"))


# Links that arrive by email land here. Each serves the app, which reads the
# token out of the URL and acts on it once it knows who is signed in.


@app.get("/join/{token}", include_in_schema=False)
def join_view(token: str) -> FileResponse:
    """Accept an invitation."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/reset/{token}", include_in_schema=False)
def reset_view(token: str) -> FileResponse:
    """Choose a new password."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
