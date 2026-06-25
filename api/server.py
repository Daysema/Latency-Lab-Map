import hashlib
import hmac
import json
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

CITIES_PATH = Path(os.environ.get("CITIES_PATH", "/data/cities.json"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-in-production")
SESSION_COOKIE = "llm_admin_session"
SESSION_VALUE = "authenticated"

VALID_STATUSES = frozenset(
    {"unknown", "ok", "temp_rare", "temp_frequent", "permanent"}
)

app = FastAPI(title="Latency Lab Map API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    password: str


class UpdateCityRequest(BaseModel):
    name: str = Field(min_length=1)
    status: str


def _session_token() -> str:
    return hmac.new(
        SESSION_SECRET.encode(),
        SESSION_VALUE.encode(),
        hashlib.sha256,
    ).hexdigest()


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    expected = _session_token()
    return hmac.compare_digest(token, expected)


def _require_admin(request: Request) -> None:
    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Админ-доступ не настроен на сервере",
        )
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="Требуется авторизация")


def _load_cities() -> list[dict]:
    if not CITIES_PATH.exists():
        raise HTTPException(status_code=500, detail="Файл городов не найден")
    return json.loads(CITIES_PATH.read_text(encoding="utf-8"))


def _save_cities(cities: list[dict]) -> None:
    CITIES_PATH.write_text(
        json.dumps(cities, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    configured = bool(ADMIN_PASSWORD)
    return {
        "authenticated": _is_authenticated(request),
        "adminConfigured": configured,
    }


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict:
    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Админ-доступ не настроен на сервере",
        )
    if not hmac.compare_digest(body.password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Неверный пароль")

    response.set_cookie(
        key=SESSION_COOKIE,
        value=_session_token(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"ok": True}


@app.patch("/api/cities")
def update_city(body: UpdateCityRequest, request: Request) -> dict:
    _require_admin(request)

    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Недопустимый статус")

    cities = _load_cities()
    updated = None
    for city in cities:
        if city["name"] == body.name:
            city["status"] = body.status
            city["statusUpdatedAt"] = date.today().isoformat()
            updated = city
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Город не найден")

    _save_cities(cities)
    return {"ok": True, "city": updated}
