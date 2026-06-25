import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

CITIES_PATH = Path(os.environ.get("CITIES_PATH", "/data/cities.json"))
REPORTS_PATH = Path(os.environ.get("REPORTS_PATH", "/data/reports.json"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-in-production")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_PROXY = os.environ.get("TELEGRAM_PROXY", "").strip()
SESSION_COOKIE = "llm_admin_session"
SESSION_VALUE = "authenticated"

VALID_STATUSES = frozenset(
    {"unknown", "ok", "temp_rare", "temp_frequent", "permanent"}
)

STATUS_LABELS = {
    "unknown": "Нет информации",
    "ok": "Нет ограничений",
    "temp_rare": "Временные ограничения (редкие)",
    "temp_frequent": "Временные ограничения (частые)",
    "permanent": "Постоянные ограничения",
}

app = FastAPI(title="Latency Lab Map API", docs_url=None, redoc_url=None)
logger = logging.getLogger("latency_lab_map")

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


class ReportRequest(BaseModel):
    city: str = Field(min_length=1, max_length=120)
    status: str | None = None
    message: str = Field(min_length=10, max_length=2000)
    contact: str | None = Field(default=None, max_length=200)


class ReviewReportRequest(BaseModel):
    apply: bool = True


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


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _load_cities() -> list[dict]:
    if not CITIES_PATH.exists():
        raise HTTPException(status_code=500, detail="Файл городов не найден")
    return _load_json(CITIES_PATH, [])


def _save_cities(cities: list[dict]) -> None:
    _save_json(CITIES_PATH, cities)


def _load_reports() -> list[dict]:
    return _load_json(REPORTS_PATH, [])


def _save_reports(reports: list[dict]) -> None:
    _save_json(REPORTS_PATH, reports)


def _telegram_proxies() -> dict[str, str] | None:
    if not TELEGRAM_PROXY:
        return None
    return {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY}


def _send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            proxies=_telegram_proxies(),
            timeout=20,
        )
        if not response.ok:
            logger.warning(
                "Telegram API returned status %s: %s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True
    except Exception:
        logger.exception("Failed to send Telegram notification")
        return False


@app.get("/api/cities")
def get_cities() -> list[dict]:
    return _load_cities()


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


@app.post("/api/reports")
def create_report(body: ReportRequest) -> dict:
    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Недопустимый статус")

    report = {
        "id": str(uuid.uuid4()),
        "city": body.city,
        "status": body.status,
        "message": body.message.strip(),
        "contact": body.contact.strip() if body.contact else None,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "reviewed": False,
    }

    reports = _load_reports()
    reports.insert(0, report)
    _save_reports(reports[:500])

    status_line = ""
    if body.status:
        status_line = f"\nСтатус: {STATUS_LABELS.get(body.status, body.status)}"

    contact_line = ""
    if body.contact:
        contact_line = f"\nКонтакт: {body.contact}"

    telegram_text = (
        "📍 Новое сообщение о ограничении\n"
        f"Город: {body.city}"
        f"{status_line}\n"
        f"Сообщение: {body.message}"
        f"{contact_line}\n"
        f"ID: {report['id']}"
    )
    telegram_sent = _send_telegram(telegram_text)

    return {"ok": True, "id": report["id"], "telegramSent": telegram_sent}


@app.get("/api/reports")
def list_reports(request: Request) -> dict:
    _require_admin(request)
    reports = _load_reports()
    pending = [r for r in reports if not r.get("reviewed")]
    return {"reports": reports[:100], "pendingCount": len(pending)}


@app.patch("/api/reports/{report_id}")
def review_report(
    report_id: str, body: ReviewReportRequest, request: Request
) -> dict:
    _require_admin(request)

    reports = _load_reports()
    report = next((r for r in reports if r["id"] == report_id), None)
    if not report:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    updated_city = None
    if body.apply and report.get("status") in VALID_STATUSES:
        cities = _load_cities()
        for city in cities:
            if city["name"] == report["city"]:
                city["status"] = report["status"]
                city["statusUpdatedAt"] = date.today().isoformat()
                updated_city = city
                break
        if updated_city:
            _save_cities(cities)

    report["reviewed"] = True
    report["reviewedAt"] = datetime.now(timezone.utc).isoformat()
    _save_reports(reports)

    return {"ok": True, "report": report, "city": updated_city}
