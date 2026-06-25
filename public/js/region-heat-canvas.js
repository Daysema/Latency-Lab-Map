const IDW_POWER = 2;
const IDW_MAX_KM = 450;

function distanceKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function pointInRing(lat, lng, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersect =
      yi > lat !== yj > lat &&
      lng < ((xj - xi) * (lat - yi)) / (yj - yi + 0.0) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function pointInFeature(lat, lng, feature) {
  const { geometry } = feature;
  if (!geometry) return false;

  if (geometry.type === "Polygon") {
    if (!pointInRing(lat, lng, geometry.coordinates[0])) return false;
    for (let h = 1; h < geometry.coordinates.length; h++) {
      if (pointInRing(lat, lng, geometry.coordinates[h])) return false;
    }
    return true;
  }

  if (geometry.type === "MultiPolygon") {
    for (const polygon of geometry.coordinates) {
      if (!pointInRing(lat, lng, polygon[0])) continue;
      let inHole = false;
      for (let h = 1; h < polygon.length; h++) {
        if (pointInRing(lat, lng, polygon[h])) {
          inHole = true;
          break;
        }
      }
      if (!inHole) return true;
    }
  }

  return false;
}

function gridStepDeg(zoom) {
  if (zoom <= 4) return 0.28;
  if (zoom <= 5) return 0.18;
  if (zoom <= 6) return 0.12;
  if (zoom <= 7) return 0.07;
  if (zoom <= 8) return 0.045;
  return 0.028;
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const full =
    value.length === 3
      ? value
          .split("")
          .map((c) => c + c)
          .join("")
      : value;
  const num = Number.parseInt(full, 16);
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function interpolateIdw(lat, lng, cities, cityStatus, intensityWeight) {
  const sources = cities.filter((c) => cityStatus(c) !== "unknown");
  if (!sources.length) return null;

  let sumW = 0;
  let sumWV = 0;

  for (const city of sources) {
    const dist = Math.max(distanceKm(lat, lng, city.lat, city.lng), 0.3);
    if (dist > IDW_MAX_KM) continue;
    const w = 1 / dist ** IDW_POWER;
    const value = intensityWeight[cityStatus(city)] ?? 0;
    sumW += w;
    sumWV += w * value;
  }

  if (sumW === 0) {
    const nearest = sources[0];
    return intensityWeight[cityStatus(nearest)] ?? 0;
  }

  return sumWV / sumW;
}

export const RegionHeatCanvas = L.Layer.extend({
  initialize(getContext) {
    this._getContext = getContext;
    this._redrawTimer = null;
  },

  onAdd(map) {
    this._map = map;
    this._canvas = L.DomUtil.create("canvas", "leaflet-region-heat");
    this._canvas.style.pointerEvents = "none";
    map.getPanes().overlayPane.appendChild(this._canvas);
    map.on("moveend zoomend resize viewreset", this._scheduleRedraw, this);
    this._scheduleRedraw();
    return this;
  },

  onRemove(map) {
    map.off("moveend zoomend resize viewreset", this._scheduleRedraw, this);
    L.DomUtil.remove(this._canvas);
    if (this._redrawTimer) {
      clearTimeout(this._redrawTimer);
      this._redrawTimer = null;
    }
  },

  redraw() {
    this._scheduleRedraw();
  },

  _scheduleRedraw() {
    if (this._redrawTimer) clearTimeout(this._redrawTimer);
    this._redrawTimer = setTimeout(() => {
      this._redrawTimer = null;
      this._redraw();
    }, 40);
  },

  _redraw() {
    const map = this._map;
    if (!map) return;

    const ctx = this._getContext();
    if (!ctx?.regionsLayer) return;

    const {
      regionsLayer,
      citiesByRegion,
      cityStatus,
      intensityWeight,
      heatColor,
      statusColors,
    } = ctx;

    const size = map.getSize();
    const canvas = this._canvas;
    canvas.width = size.x;
    canvas.height = size.y;

    const topLeft = map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(canvas, topLeft);

    const g = canvas.getContext("2d");
    g.clearRect(0, 0, size.x, size.y);

    const viewBounds = map.getBounds();
    const zoom = map.getZoom();
    const step = gridStepDeg(zoom);

    regionsLayer.eachLayer((layer) => {
      const feature = layer.feature;
      if (!feature) return;

      const bounds = layer.getBounds();
      if (!viewBounds.intersects(bounds)) return;

      const regionName = feature.properties.name;
      const cities = citiesByRegion[regionName] || [];
      const known = cities.filter((c) => cityStatus(c) !== "unknown");

      const south = bounds.getSouth();
      const north = bounds.getNorth();
      const west = bounds.getWest();
      const east = bounds.getEast();

      for (let lat = south; lat <= north; lat += step) {
        for (let lng = west; lng <= east; lng += step) {
          if (!viewBounds.contains([lat, lng])) continue;
          if (!pointInFeature(lat, lng, feature)) continue;

          let fill;
          if (!known.length) {
            if (!cities.length) continue;
            fill = hexToRgba(statusColors.unknown, 0.1);
          } else {
            const intensity = interpolateIdw(
              lat,
              lng,
              cities,
              cityStatus,
              intensityWeight
            );
            if (intensity === null) continue;
            if (intensity <= 0.02) {
              fill = hexToRgba(statusColors.ok, 0.22 + (1 - intensity) * 0.08);
            } else {
              fill = hexToRgba(heatColor(intensity), 0.12 + intensity * 0.42);
            }
          }

          const pt = map.latLngToContainerPoint([lat, lng]);
          const pt2 = map.latLngToContainerPoint([lat + step, lng + step]);
          const w = Math.max(2, Math.abs(pt2.x - pt.x) + 1);
          const h = Math.max(2, Math.abs(pt2.y - pt.y) + 1);

          g.fillStyle = fill;
          g.fillRect(pt.x, pt.y, w, h);
        }
      }
    });
  },
});

export function createRegionHeatLayer(getContext) {
  return new RegionHeatCanvas(getContext);
}
