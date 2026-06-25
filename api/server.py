import hashlib
import hmac
import json
import logging
import os
import threading
import time
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
TELEGRAM_TOPIC_ID = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
TELEGRAM_TOPIC_ID_OPS = os.environ.get("TELEGRAM_TOPIC_ID_OPS", "").strip()
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
_reports_lock = threading.Lock()
_cities_lock = threading.Lock()

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
    message: str = Field(default="", max_length=2000)
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

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if "Extra data" in exc.msg:
            decoder = json.JSONDecoder()
            data, end = decoder.raw_decode(text)
            logger.warning(
                "Repaired JSON with trailing data in %s at char %s",
                path,
                end,
            )
            _save_json(path, data)
            return data

        backup = path.with_name(
            f"{path.stem}.corrupt.{int(time.time())}{path.suffix}"
        )
        path.replace(backup)
        logger.error("Corrupt JSON in %s, backed up to %s", path, backup)
        _send_telegram(
            f"⚠️ Ошибка данных на карте\n"
            f"Файл: {path.name}\n"
            f"Резервная копия: {backup.name}\n"
            f"Использованы значения по умолчанию.",
            topic="ops",
        )
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    content = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path.write_text(content, encoding="utf-8")
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


def _parse_topic_id(value: str) -> int | None:
    if not value:
        return None
    try:
        topic_id = int(value)
    except ValueError:
        logger.warning("Invalid Telegram topic id: %r", value)
        return None
    if topic_id <= 0:
        logger.warning("Telegram topic id must be positive: %s", topic_id)
        return None
    return topic_id


def _telegram_proxies() -> dict[str, str] | None:
    if not TELEGRAM_PROXY:
        return None
    return {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY}


def _send_telegram(text: str, *, topic: str = "reports") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    thread_id = _parse_topic_id(
        TELEGRAM_TOPIC_ID_OPS if topic == "ops" else TELEGRAM_TOPIC_ID
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: dict[str, object] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    try:
        response = requests.post(
            url,
            data=payload,
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


def _report_telegram_topic(status: str | None) -> str:
    """Уточнения и исправления карты — в отдельный топик."""
    if status in (None, "ok"):
        return "ops"
    return "reports"


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

    with _cities_lock:
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

    with _reports_lock:
        reports = _load_reports()
        if not isinstance(reports, list):
            reports = []
        reports.insert(0, report)
        _save_reports(reports[:500])

    status_line = ""
    if body.status:
        status_line = f"\nСтатус: {STATUS_LABELS.get(body.status, body.status)}"

    contact_line = ""
    if body.contact:
        contact_line = f"\nКонтакт: {body.contact}"

    topic = _report_telegram_topic(body.status)
    if topic == "ops":
        if body.status == "ok":
            headline = "✏️ Уточнение: на карте ошибка (нет ограничений)"
        else:
            headline = "❓ Уточнение по городу"
    else:
        headline = "📍 Новое сообщение об ограничении"

    telegram_text = (
        f"{headline}\n"
        f"Город: {body.city}"
        f"{status_line}\n"
        f"Сообщение: {body.message.strip() or '—'}"
        f"{contact_line}\n"
        f"ID: {report['id']}"
    )
    telegram_sent = _send_telegram(telegram_text, topic=topic)

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

    with _reports_lock:
        reports = _load_reports()
        if not isinstance(reports, list):
            reports = []
        report = next((r for r in reports if r["id"] == report_id), None)
        if not report:
            raise HTTPException(status_code=404, detail="Заявка не найдена")

        updated_city = None
        if body.apply and report.get("status") in VALID_STATUSES:
            with _cities_lock:
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
