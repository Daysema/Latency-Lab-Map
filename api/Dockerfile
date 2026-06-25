FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/server.py .
COPY api/merge_extra_cities.py .
COPY api/merge_extra_regions.py .
COPY api/entrypoint.sh /entrypoint.sh
COPY public/data/ /seed/

RUN chmod +x /entrypoint.sh

ENV CITIES_PATH=/data/cities.json

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
