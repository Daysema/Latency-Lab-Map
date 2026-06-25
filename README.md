# Latency Lab Map

Веб-карта России с границами субъектов Федерации и городами. Развёртывание через Docker.

## Возможности

- Интерактивная карта России с зумом до уровня города (без улиц)
- Границы 85 субъектов РФ
- 1100+ городов с категориями: столицы, миллионники, крупные, областные центры, малые
- Поиск города по названию
- Тёмная тема

## Быстрый старт

### 1. Подготовить данные

```bash
python scripts/prepare_data.py
```

### 2. Запустить в Docker

```bash
docker compose up --build
```

Сайт будет доступен по адресу: **http://localhost:8080**

## Локальная разработка без Docker

После подготовки данных можно открыть `public/index.html` через любой статический сервер:

```bash
cd public
python -m http.server 8000
```

## Структура

```
├── docker-compose.yml
├── Dockerfile
├── nginx.conf
├── public/
│   ├── index.html
│   ├── css/style.css
│   ├── js/app.js
│   └── data/          # cities.json, regions.geojson (генерируются скриптом)
└── scripts/
    └── prepare_data.py
```

## Источники данных

- Границы субъектов: [Natural Earth](https://www.naturalearthdata.com/)
- Города: [pensnarik/russian-cities](https://github.com/pensnarik/russian-cities)
- Подложка карты: [CARTO](https://carto.com/) / OpenStreetMap
