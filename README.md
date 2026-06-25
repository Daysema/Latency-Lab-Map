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
- Открытый порт **8080** (или **80**, если измените в `docker-compose.yml`)
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

### Шаг 5. Настроить пароль администратора

Только вы сможете менять статусы доступности на карте. Создайте файл `.env`:

```bash
cp .env.example .env
nano .env
```

Задайте надёжный пароль:

```
ADMIN_PASSWORD=ваш-секретный-пароль
SESSION_SECRET=случайная-длинная-строка-минимум-32-символа
```

### Шаг 6. Запустить сайт

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
http://IP_ВАШЕГО_СЕРВЕРА:8080
```

### Шаг 7. Открыть порт в файрволе (если включён ufw)

```bash
sudo ufw allow 8080/tcp
sudo ufw status
```

Если нужен стандартный порт 80, откройте его и измените проброс в `docker-compose.yml`:

```yaml
ports:
  - "80:80"
```

Затем перезапустите:

```bash
docker compose down
docker compose up -d
```

---

## Редактирование статусов (только администратор)

1. Откройте карту в браузере
2. Нажмите кнопку 🔒 в правом верхнем углу
3. Введите пароль из `.env` (`ADMIN_PASSWORD`)
4. Кликните на город → выберите статус → **Сохранить**

Дата обновления проставится автоматически. Цвет маркера и региона обновится сразу.

Чтобы выйти из режима редактирования, нажмите ✏️ в шапке.

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

Сайт: **http://localhost:8080**

### Локально без Docker

```bash
cd public
python -m http.server 8000
```

Сайт: **http://localhost:8000**

---

## Структура проекта

```
├── docker-compose.yml   # nginx + API
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
