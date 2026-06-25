const HEAT_MIN_ZOOM = 5;
const HEAT_MAX_REGIONS = 10;
const HEAT_DEBOUNCE_MS = 280;

export function createRegionHeatController(map) {
  const overlays = new Map();
  const loading = new Set();
  let regionsLayer = null;
  let heatVersion = 0;
  let timer = null;
  let paneReady = false;

  function ensurePane() {
    if (paneReady) return;
    if (!map.getPane("regionHeatPane")) {
      map.createPane("regionHeatPane");
      map.getPane("regionHeatPane").style.zIndex = 360;
    }
    paneReady = true;
  }

  function clearOverlays() {
    for (const overlay of overlays.values()) {
      map.removeLayer(overlay);
    }
    overlays.clear();
    loading.clear();
  }

  function invalidate() {
    heatVersion += 1;
    clearOverlays();
    scheduleUpdate();
  }

  function setRegionsLayer(layer) {
    regionsLayer = layer;
  }

  function restoreRegionFills() {
    if (!regionsLayer) return;
    regionsLayer.eachLayer((layer) => {
      if (!layer._baseRegionStyle) return;
      layer.setStyle(layer._baseRegionStyle);
    });
  }

  function hideFillsFor(names) {
    if (!regionsLayer) return;
    regionsLayer.eachLayer((layer) => {
      const name = layer.feature?.properties?.name;
      if (!names.has(name) || !layer._baseRegionStyle) return;
      layer.setStyle({
        ...layer._baseRegionStyle,
        fillOpacity: 0,
        fillColor: "transparent",
      });
    });
  }

  function scheduleUpdate() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(update, HEAT_DEBOUNCE_MS);
  }

  function visibleRegionLayers() {
    if (!regionsLayer) return [];
    const view = map.getBounds();
    const layers = [];
    regionsLayer.eachLayer((layer) => {
      if (view.intersects(layer.getBounds())) {
        layers.push(layer);
      }
    });
    return layers;
  }

  function loadHeat(layer) {
    const name = layer.feature.properties.name;
    if (overlays.has(name) || loading.has(name)) return;

    loading.add(name);
    ensurePane();

    const bounds = layer.getBounds();
    const url = `/api/regions/heat?name=${encodeURIComponent(name)}&w=180&v=${heatVersion}`;

    const overlay = L.imageOverlay(url, bounds, {
      pane: "regionHeatPane",
      opacity: 0.92,
      interactive: false,
      className: "region-heat-overlay",
    });

    overlay.once("load", () => {
      loading.delete(name);
    });
    overlay.once("error", () => {
      loading.delete(name);
      map.removeLayer(overlay);
      overlays.delete(name);
      if (layer._baseRegionStyle) {
        layer.setStyle(layer._baseRegionStyle);
      }
    });

    overlay.addTo(map);
    overlays.set(name, overlay);
  }

  function update() {
    timer = null;
    if (!regionsLayer) return;

    const zoom = map.getZoom();
    if (zoom < HEAT_MIN_ZOOM) {
      clearOverlays();
      restoreRegionFills();
      return;
    }

    const layers = visibleRegionLayers()
      .sort((a, b) => {
        const center = map.getCenter();
        const da = center.distanceTo(a.getBounds().getCenter());
        const db = center.distanceTo(b.getBounds().getCenter());
        return da - db;
      })
      .slice(0, HEAT_MAX_REGIONS);

    const keep = new Set(layers.map((layer) => layer.feature.properties.name));

    for (const [name, overlay] of overlays) {
      if (!keep.has(name)) {
        map.removeLayer(overlay);
        overlays.delete(name);
      }
    }

    hideFillsFor(keep);

    for (const layer of layers) {
      loadHeat(layer);
    }
  }

  map.on("zoomend moveend", scheduleUpdate);

  return {
    setRegionsLayer,
    invalidate,
    update,
    clear: clearOverlays,
    hasOverlay: (name) => overlays.has(name),
  };
}
