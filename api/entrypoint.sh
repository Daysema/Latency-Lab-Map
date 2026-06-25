#!/bin/sh
set -e

mkdir -p /data

if [ ! -f /data/cities.json ]; then
  echo "Initializing cities.json in persistent volume..."
  cp /seed/cities.json /data/cities.json
fi

if [ ! -f /data/regions.geojson ]; then
  echo "Initializing regions.geojson in persistent volume..."
  cp /seed/regions.geojson /data/regions.geojson
fi

if [ ! -f /data/reports.json ]; then
  echo "Initializing reports.json in persistent volume..."
  echo "[]" > /data/reports.json
fi

python3 merge_extra_cities.py

exec uvicorn server:app --host 0.0.0.0 --port 8000
