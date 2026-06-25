import hashlib
import hmac
import io
import json
import logging
import os
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

CITIES_PATH = Path(os.environ.get("CITIES_PATH", "/data/cities.json"))
REPORTS_PATH = Path(os.environ.get("REPORTS_PATH", "/data/reports.json"))
REGIONS_PATH = Path(os.environ.get("REGIONS_PATH", "/data/regions.geojson"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
BACKUP_INTERVAL_HOURS = float(os.environ.get("TELEGRAM_BACKUP_INTERVAL_HOURS", "0") or "0")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-in-production")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_TOPIC_ID = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
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

logger = logging.getLogger("latency_lab_map")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (
        BACKUP_INTERVAL_HOURS > 0
        and TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
    ):
        thread = threading.Thread(target=_scheduled_backup_loop, daemon=True)
        thread.start()
        logger.info(
            "Telegram backup scheduled every %s h",
            BACKUP_INTERVAL_HOURS,
        )
    yield


app = FastAPI(
    title="Latency Lab Map API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
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
    comment: str | None = Field(default=None, max_length=500)


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


def _load_pending_reports() -> list[dict]:
    reports = _load_reports()
    if not isinstance(reports, list):
        reports = []
    pending = [r for r in reports if not r.get("reviewed")]
    if len(pending) != len(reports):
        _save_reports(pending)
    return pending


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


def _telegram_payload_base() -> dict[str, object] | None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    payload: dict[str, object] = {"chat_id": TELEGRAM_CHAT_ID}
    thread_id = _parse_topic_id(TELEGRAM_TOPIC_ID)
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    return payload


def _send_telegram(text: str) -> bool:
    payload = _telegram_payload_base()
    if payload is None:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload["text"] = text
    payload["disable_web_page_preview"] = True

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


def _send_telegram_document(
    file_data: bytes, filename: str, caption: str
) -> bool:
    payload = _telegram_payload_base()
    if payload is None:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    payload["caption"] = caption[:1024]

    try:
        response = requests.post(
            url,
            data=payload,
            files={"document": (filename, file_data)},
            proxies=_telegram_proxies(),
            timeout=120,
        )
        if not response.ok:
            logger.warning(
                "Telegram document API returned status %s: %s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True
    except Exception:
        logger.exception("Failed to send Telegram document")
        return False


BACKUP_FILES: tuple[tuple[str, Path], ...] = (
    ("cities.json", CITIES_PATH),
    ("reports.json", REPORTS_PATH),
    ("regions.geojson", REGIONS_PATH),
)

RESTORE_README = """Резервная копия Latency Lab Map
==============================

Восстановление на новом сервере:
1. Распакуйте cities.json, reports.json и regions.geojson в Docker-volume /data/
   (в docker-compose это volume map_data, путь внутри контейнера api: /data/).
2. Запустите: docker compose up -d

Статические файлы из репозитория (public/data/) — только начальные данные;
рабочая копия хранится в volume и переживает пересборку контейнеров.
"""


def _build_backup_archive() -> tuple[bytes, str, list[str]]:
    included: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("RESTORE.txt", RESTORE_README)
        for arcname, path in BACKUP_FILES:
            if path.exists():
                archive.write(path, arcname)
                included.append(arcname)

    if not included:
        raise HTTPException(
            status_code=500,
            detail="Нет файлов данных для резервной копии",
        )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    filename = f"latency-lab-map_{stamp}_utc.zip"
    return buf.getvalue(), filename, included


def _backup_to_telegram(*, manual: bool) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(
            status_code=503,
            detail="Telegram не настроен (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)",
        )

    zip_data, filename, included = _build_backup_archive()
    size_kb = len(zip_data) // 1024
    kind = "Ручная выгрузка" if manual else "Автоматическая выгрузка"
    caption = (
        f"💾 {kind} БД карты\n"
        f"Файлы: {', '.join(included)}\n"
        f"Размер: {size_kb} КБ\n"
        f"Распакуйте в /data/ на новом сервере (см. RESTORE.txt в архиве)."
    )
    sent = _send_telegram_document(zip_data, filename, caption)
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Не удалось отправить архив в Telegram",
        )

    logger.info("Backup sent to Telegram: %s (%s KB)", filename, size_kb)
    return {
        "ok": True,
        "filename": filename,
        "files": included,
        "sizeBytes": len(zip_data),
        "telegramSent": sent,
    }


def _scheduled_backup_loop() -> None:
    while True:
        time.sleep(max(BACKUP_INTERVAL_HOURS, 0.1) * 3600)
        try:
            _backup_to_telegram(manual=False)
        except HTTPException as exc:
            logger.warning("Scheduled backup skipped: %s", exc.detail)
        except Exception:
            logger.exception("Scheduled backup failed")


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
                comment = (body.comment or "").strip()
                city["comment"] = comment or None
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
    }

    with _reports_lock:
        reports = _load_pending_reports()
        reports.insert(0, report)
        _save_reports(reports[:500])

    status_line = ""
    if body.status:
        status_line = f"\nСтатус: {STATUS_LABELS.get(body.status, body.status)}"

    contact_line = ""
    if body.contact:
        contact_line = f"\nКонтакт: {body.contact}"

    if body.status == "ok":
        headline = "✏️ Уточнение: на карте ошибка (нет ограничений)"
    elif not body.status:
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
    telegram_sent = _send_telegram(telegram_text)

    return {"ok": True, "id": report["id"], "telegramSent": telegram_sent}


@app.get("/api/reports")
def list_reports(request: Request) -> dict:
    _require_admin(request)
    reports = _load_pending_reports()
    return {"reports": reports[:100], "pendingCount": len(reports)}


@app.post("/api/admin/backup")
def admin_backup(request: Request) -> dict:
    _require_admin(request)
    return _backup_to_telegram(manual=True)


@app.patch("/api/reports/{report_id}")
def review_report(
    report_id: str, body: ReviewReportRequest, request: Request
) -> dict:
    _require_admin(request)

    with _reports_lock:
        reports = _load_pending_reports()
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

        reports = [r for r in reports if r["id"] != report_id]
        _save_reports(reports)

    return {"ok": True, "report": report, "city": updated_city}
