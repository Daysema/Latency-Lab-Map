# Latency Lab Map

Веб-карта России с границами субъектов Федерации и городами. Развёртывание через Docker.

## Возможности

- Интерактивная карта России с зумом до уровня города (без улиц)
- Границы 85 субъектов РФ
- 1100+ городов с категориями: столицы, миллионники, крупные, областные центры, малые
- Поиск города по названию
- Тёмная тема

---

## Установка на Ubuntu Server

Ниже — полная пошаговая инструкция: от чистого сервера до работающего сайта.

### Требования

- Ubuntu 22.04 / 24.04 (или другой Debian-based дистрибутив)
- Минимум 1 ГБ RAM, 2 ГБ диска
- Домен с A-записью на IP сервера (для HTTPS)
- Открытые порты **80** и **443** (Caddy + Let's Encrypt)
- Доступ по SSH

### Шаг 1. Подключиться к серверу

```bash
ssh user@IP_ВАШЕГО_СЕРВЕРА
```

### Шаг 2. Обновить систему и установить Git

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git ca-certificates curl
```

### Шаг 3. Установить Docker

Официальный способ установки Docker Engine на Ubuntu:

```bash
# Удалить старые версии (если были)
sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null

# Добавить репозиторий Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${VERSION_CODENAME:-$VERSION_ID}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установить Docker и плагин Compose
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Проверить установку
sudo docker --version
sudo docker compose version
```

Добавить текущего пользователя в группу `docker` (чтобы не писать `sudo` каждый раз):

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Проверка, что Docker работает:

```bash
docker run --rm hello-world
```

### Шаг 4. Скопировать проект с GitHub

```bash
cd ~
git clone https://github.com/Daysema/Latency-Lab-Map.git
cd Latency-Lab-Map
```

> Данные карты (`cities.json`, `regions.geojson`) уже включены в репозиторий — отдельно ничего скачивать не нужно.

### Шаг 5. Настроить `.env`

```bash
cp .env.example .env
nano .env
```

Пример для продакшена с доменом:

```
SITE_ADDRESS=map.example.com
ACME_EMAIL=ваш-настоящий@email.com
ADMIN_PASSWORD=ваш-секретный-пароль
SESSION_SECRET=случайная-длинная-строка-минимум-32-символа
```

- `SITE_ADDRESS` — ваш домен (Caddy выпустит HTTPS-сертификат автоматически)
- `ACME_EMAIL` — **реальный** email для Let's Encrypt (нельзя `example.com`)

Для проверки по IP без домена (только HTTP):

```
SITE_ADDRESS=:80
```

### Шаг 6. DNS

В панели регистратора домена создайте **A-запись**:

```
map.example.com  →  IP_ВАШЕГО_СЕРВЕРА
```

Подождите 5–30 минут, пока DNS обновится.

### Шаг 7. Запустить сайт

```bash
docker compose up --build -d
```

Проверить, что контейнер запущен:

```bash
docker compose ps
docker compose logs -f
```

(`Ctrl+C` — выйти из просмотра логов, контейнер продолжит работать.)

Сайт будет доступен по адресу:

```
https://map.example.com
```

### Шаг 8. Открыть порты в файрволе (если включён ufw)

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

Затем перезапустите при необходимости:

```bash
docker compose down
docker compose up -d
```

### HTTPS не работает / ошибка сертификата

Если в логах Caddy есть `contact email has forbidden domain "example.com"`:

1. Откройте `.env` и укажите **настоящий** email:
   ```bash
   nano .env
   ```
   ```
   ACME_EMAIL=ваш@gmail.com
   SITE_ADDRESS=map.latencylab.ru
   ```

2. Перезапустите Caddy:
   ```bash
   docker compose up -d caddy
   ```

3. Проверьте логи (сертификат выпускается за 1–2 минуты):
   ```bash
   docker compose logs -f caddy
   ```

Убедитесь, что DNS A-запись домена указывает на IP сервера и порты 80/443 открыты.

---

## Редактирование статусов (только администратор)

1. Откройте карту в браузере
2. Нажмите кнопку 🔒 в правом верхнем углу
3. Введите пароль из `.env` (`ADMIN_PASSWORD`)
4. Кликните на город → выберите статус → **Сохранить**

Дата обновления проставится автоматически. Цвет маркера и региона обновится сразу.

Чтобы выйти из режима редактирования, нажмите ✏️ в шапке.

### Сообщения от пользователей

Кнопка **«Сообщить об ограничении»** в легенде открывает форму. Заявки сохраняются в `/data/reports.json` в Docker-томе.

Для уведомлений в Telegram добавьте в `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=ваш_chat_id
TELEGRAM_PROXY=socks5://user:pass@host:1080
```

Если `api.telegram.org` с сервера не открывается напрямую, укажите прокси в `TELEGRAM_PROXY` (HTTP, HTTPS или SOCKS5).

Просмотр очереди (только для админа после входа):

```bash
curl -b cookies.txt -c cookies.txt -X POST https://map.example.com/api/auth/login \
  -H "Content-Type: application/json" -d '{"password":"ваш-пароль"}'
curl -b cookies.txt https://map.example.com/api/reports
```

### Тепловая карта субъектов

Заливка региона показывает **интенсивность ограничений** по городам внутри субъекта:
- серый — нет данных
- зелёный — города без ограничений
- жёлтый → оранжевый → красный — нарастающая интенсивность

Наведите на субъект для краткой сводки, кликните для подробной статистики.

> Без файла `.env` с паролем редактирование недоступно никому — карта только для просмотра.

Данные о статусах городов хранятся в Docker-томе `map_data` и **не сбрасываются** при `git pull` или пересборке контейнера.

### Резервная копия данных

```bash
docker compose exec api cat /data/cities.json > cities-backup.json
```

---

## Полезные команды на сервере

### Остановить сайт

```bash
cd ~/Latency-Lab-Map
docker compose down
```

### Перезапустить

```bash
cd ~/Latency-Lab-Map
docker compose restart
```

### Обновить до последней версии с GitHub

```bash
cd ~/Latency-Lab-Map
git pull
docker compose up --build -d
```

### Посмотреть логи

```bash
cd ~/Latency-Lab-Map
docker compose logs -f
```

### Автозапуск при перезагрузке сервера

Docker обычно стартует сам (`systemctl enable docker`). Контейнер поднимется автоматически благодаря `restart: unless-stopped` в `docker-compose.yml`.

Проверить:

```bash
sudo systemctl enable docker
sudo systemctl status docker
```

---

## Быстрый старт (локально, Windows / macOS)

### 1. Подготовить данные (опционально — для обновления городов)

```bash
python scripts/prepare_data.py
```

### 2. Запустить в Docker

```bash
docker compose up --build
```

Сайт: **http://localhost** (при `SITE_ADDRESS=:80` в `.env`)

### Локально без Docker

```bash
cd public
python -m http.server 8000
```

Сайт: **http://localhost:8000**

---

## Структура проекта

```
├── Caddyfile            # reverse proxy + HTTPS
├── docker-compose.yml   # caddy + nginx + API
├── Dockerfile           # образ nginx со статикой
├── api/                 # бэкенд для сохранения статусов
├── nginx.conf
├── .env.example         # шаблон пароля администратора
├── public/
│   ├── js/admin.js      # авторизация и API
│   └── data/            # cities.json (общий volume с API)
└── scripts/
    └── prepare_data.py
```

## Источники данных

- Границы субъектов: [Natural Earth](https://www.naturalearthdata.com/)
- Города: [pensnarik/russian-cities](https://github.com/pensnarik/russian-cities)
- Подложка карты: [CARTO](https://carto.com/) / OpenStreetMap
