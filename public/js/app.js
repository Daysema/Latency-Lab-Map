import { initAdmin, isAdmin, onAdminChange, updateCityStatus } from "./admin.js";
import { initReports } from "./reports.js";

const STATUS_LABELS = {
  unknown: "Нет информации",
  ok: "Нет ограничений",
  temp_rare: "Временные ограничения (редкие)",
  temp_frequent: "Временные ограничения (частые)",
  permanent: "Постоянные ограничения",
};

const STATUS_COLORS = {
  unknown: "#94a3b8",
  ok: "#22c55e",
  temp_rare: "#eab308",
  temp_frequent: "#f97316",
  permanent: "#ef4444",
};

const INTENSITY_WEIGHT = {
  unknown: 0,
  ok: 0,
  temp_rare: 0.35,
  temp_frequent: 0.65,
  permanent: 1,
};

const HEAT_STOPS = [
  { t: 0, rgb: [100, 116, 139] },
  { t: 0.25, rgb: [34, 197, 94] },
  { t: 0.5, rgb: [234, 179, 8] },
  { t: 0.75, rgb: [249, 115, 22] },
  { t: 1, rgb: [239, 68, 68] },
];

/** City subject names → region names in GeoJSON */
const SUBJECT_ALIASES = {
  Алтай: "Республика Алтай",
  Башкортостан: "Республика Башкортостан",
  Коми: "Республика Коми",
  Крым: "Автономная Республика Крым",
  ДНР: "Донецкая Народная Республика",
  ЛНР: "Луганская Народная Республика",
  "Северная Осетия": "Республика Северная Осетия-Алания",
  "Еврейская АО": "Еврейская автономная область",
  "Ненецкий АО": "Ненецкий автономный округ",
  "Ханты-Мансийский АО": "Ханты-Мансийский автономный округ — Югра",
  "Чукотский АО": "Чукотский автономный округ",
  "Ямало-Ненецкий АО": "Ямало-Ненецкий автономный округ",
};

const TIER_RADIUS = {
  capital: 9,
  megacity: 8,
  large: 7,
  regional: 6,
  small: 5,
  town: 4,
};

/** Minimum zoom to show each city tier (by population) */
const TIER_MIN_ZOOM = {
  capital: 3,
  megacity: 4,
  large: 5,
  regional: 6,
  small: 7,
  town: 8,
};

const MIN_ZOOM = 3;
const MAX_ZOOM = 10; // city level — no street detail

/** Initial framing — all of Russia without empty Arctic ocean above */
const RUSSIA_INITIAL_BOUNDS = [
  [41.5, 19.0],
  [70.0, 170.0],
];

const map = L.map("map", {
  minZoom: MIN_ZOOM,
  maxZoom: MAX_ZOOM,
  zoomControl: true,
});

map.fitBounds(RUSSIA_INITIAL_BOUNDS, { padding: [16, 16], maxZoom: 4 });
map.attributionControl.setPrefix("");

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
    '&copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: "abcd",
  minZoom: MIN_ZOOM,
  maxZoom: MAX_ZOOM,
}).addTo(map);

const cityLayer = L.layerGroup().addTo(map);
const zoomLevelEl = document.getElementById("zoom-level");
const searchInput = document.getElementById("city-search");
const searchResults = document.getElementById("search-results");
const popup = document.getElementById("city-popup");
const popupAdmin = document.getElementById("popup-admin");
const popupStatusSelect = document.getElementById("popup-status-select");
const popupCommentInput = document.getElementById("popup-comment-input");
const popupCommentRow = document.getElementById("popup-comment-row");
const popupCommentEl = document.getElementById("popup-comment");
const popupSaveBtn = document.getElementById("popup-save");
const popupAdminError = document.getElementById("popup-admin-error");
const regionPopup = document.getElementById("region-popup");

let allCities = [];
let cityMarkers = new Map();
let regionStatsMap = {};
let regionsLayer = null;
let activeCity = null;
let activeRegionName = null;
let reportActions = null;

function cityStatus(city) {
  return city.status || "unknown";
}

function normalizeSubject(subject) {
  return SUBJECT_ALIASES[subject] || subject;
}

function rgbToHex([r, g, b]) {
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function heatColor(intensity) {
  const value = Math.max(0, Math.min(1, intensity));
  for (let i = 0; i < HEAT_STOPS.length - 1; i++) {
    const left = HEAT_STOPS[i];
    const right = HEAT_STOPS[i + 1];
    if (value <= right.t) {
      const localT = (value - left.t) / (right.t - left.t || 1);
      const rgb = left.rgb.map((channel, idx) =>
        Math.round(lerp(left.rgb[idx], right.rgb[idx], localT))
      );
      return rgbToHex(rgb);
    }
  }
  return rgbToHex(HEAT_STOPS[HEAT_STOPS.length - 1].rgb);
}

function computeIntensity(counts, total) {
  if (!total) return 0;
  const unknown = counts.unknown || 0;
  const known = total - unknown;
  if (!known) return 0;

  let sum = 0;
  for (const [status, count] of Object.entries(counts)) {
    if (status === "unknown") continue;
    sum += (INTENSITY_WEIGHT[status] ?? 0) * count;
  }
  return sum / known;
}

function regionHeatVisual(stats) {
  const { counts, total, intensity } = stats;
  const unknown = counts.unknown || 0;
  const known = total - unknown;
  const restricted =
    (counts.temp_rare || 0) +
    (counts.temp_frequent || 0) +
    (counts.permanent || 0);

  if (!known) {
    return {
      color: heatColor(0),
      fillIntensity: total > 0 ? 0.22 : 0,
    };
  }

  if (!restricted && (counts.ok || 0) > 0) {
    return {
      color: STATUS_COLORS.ok,
      fillIntensity: 0.12 + ((counts.ok || 0) / total) * 0.25,
    };
  }

  return {
    color: heatColor(intensity),
    fillIntensity: intensity,
  };
}

function worstStatusFromCounts(counts) {
  let worst = "unknown";
  let maxWeight = -1;
  for (const [status, count] of Object.entries(counts)) {
    if (!count) continue;
    const weight = INTENSITY_WEIGHT[status] ?? 0;
    if (weight > maxWeight) {
      maxWeight = weight;
      worst = status;
    }
  }
  return worst;
}

function buildRegionStatsMap(cities) {
  const map = {};
  for (const city of cities) {
    const region = normalizeSubject(city.subject || "");
    if (!region) continue;
    if (!map[region]) {
      map[region] = {
        counts: {
          unknown: 0,
          ok: 0,
          temp_rare: 0,
          temp_frequent: 0,
          permanent: 0,
        },
        total: 0,
        intensity: 0,
        worstStatus: "unknown",
      };
    }
    const status = cityStatus(city);
    map[region].counts[status] = (map[region].counts[status] || 0) + 1;
    map[region].total += 1;
  }

  for (const stats of Object.values(map)) {
    stats.intensity = computeIntensity(stats.counts, stats.total);
    stats.worstStatus = worstStatusFromCounts(stats.counts);
  }
  return map;
}

function getRegionStats(feature) {
  const name = feature.properties.name;
  return (
    regionStatsMap[name] || {
      counts: { unknown: 0, ok: 0, temp_rare: 0, temp_frequent: 0, permanent: 0 },
      total: 0,
      intensity: 0,
      worstStatus: "unknown",
    }
  );
}

function formatIntensityPercent(intensity) {
  return `${Math.round(intensity * 100)}%`;
}

function formatRegionTooltip(name, stats) {
  const lines = [
    `<strong>${name}</strong>`,
    `Интенсивность: ${formatIntensityPercent(stats.intensity)}`,
    `Городов на карте: ${stats.total}`,
  ];

  const statusOrder = ["permanent", "temp_frequent", "temp_rare", "ok", "unknown"];
  for (const status of statusOrder) {
    const count = stats.counts[status] || 0;
    if (count > 0) {
      lines.push(`${STATUS_LABELS[status]}: ${count}`);
    }
  }

  lines.push('<span style="opacity:0.75">Клик — подробная сводка</span>');
  return lines.join("<br>");
}

function regionStyleForHeat(stats) {
  const { color, fillIntensity } = regionHeatVisual(stats);
  return {
    fillColor: color,
    fillOpacity: 0.08 + fillIntensity * 0.48,
    color,
    weight: 1.2 + fillIntensity * 1.4,
    opacity: 0.55 + fillIntensity * 0.45,
  };
}

function regionHoverStyle(stats) {
  const { color, fillIntensity } = regionHeatVisual(stats);
  return {
    fillColor: color,
    fillOpacity: 0.2 + fillIntensity * 0.58,
    color,
    weight: 2.2 + fillIntensity * 1.2,
    opacity: 1,
  };
}

function formatPopulation(n) {
  return new Intl.NumberFormat("ru-RU").format(n) + " чел.";
}

function formatStatusUpdatedAt(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
}

function createCityIcon(city) {
  const status = cityStatus(city);
  const radius = TIER_RADIUS[city.tier] || 5;
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;

  return L.divIcon({
    className: `city-marker city-marker--${status}`,
    html: `<span style="
      display:block;
      width:${radius * 2}px;
      height:${radius * 2}px;
      margin:${-radius}px 0 0 ${-radius}px;
      background:${color};
      border:2px solid rgba(255,255,255,0.85);
      border-radius:50%;
      box-shadow:0 0 6px rgba(0,0,0,0.5);
    "></span>`,
    iconSize: [radius * 2, radius * 2],
    iconAnchor: [radius, radius],
  });
}

function showCityPopup(city) {
  activeCity = city;
  hideRegionPopup();
  document.getElementById("popup-name").textContent = city.name;
  document.getElementById("popup-subject").textContent = city.subject || "—";
  document.getElementById("popup-population").textContent = formatPopulation(
    city.population
  );
  document.getElementById("popup-status").textContent =
    STATUS_LABELS[cityStatus(city)] || cityStatus(city);
  document.getElementById("popup-updated").textContent = formatStatusUpdatedAt(
    city.statusUpdatedAt
  );

  const comment = (city.comment || "").trim();
  if (comment) {
    popupCommentEl.textContent = comment;
    popupCommentRow.hidden = false;
  } else {
    popupCommentEl.textContent = "";
    popupCommentRow.hidden = true;
  }

  if (isAdmin()) {
    popupAdmin.hidden = false;
    popupStatusSelect.value = cityStatus(city);
    popupCommentInput.value = comment;
    popupAdminError.hidden = true;
  } else {
    popupAdmin.hidden = true;
  }

  popup.hidden = false;
}

function hideCityPopup() {
  popup.hidden = true;
  activeCity = null;
  popupAdminError.hidden = true;
}

function hideRegionPopup() {
  regionPopup.hidden = true;
  activeRegionName = null;
}

function showRegionPopup(name, stats) {
  hideCityPopup();
  activeRegionName = name;

  document.getElementById("region-popup-name").textContent = name;
  document.getElementById("region-popup-intensity").textContent =
    `Интенсивность ограничений: ${formatIntensityPercent(stats.intensity)}`;

  const statsList = document.getElementById("region-popup-stats");
  statsList.innerHTML = "";
  for (const [status, label] of Object.entries(STATUS_LABELS)) {
    const count = stats.counts[status] || 0;
    if (!count) continue;
    const li = document.createElement("li");
    li.innerHTML = `<span class="dot dot--${status === "temp_rare" ? "temp-rare" : status === "temp_frequent" ? "temp-frequent" : status}"></span>${label}: <strong>${count}</strong>`;
    statsList.appendChild(li);
  }

  document.getElementById("region-popup-total").textContent =
    `Всего городов на карте: ${stats.total}`;
  regionPopup.hidden = false;
}

function refreshRegionStyles() {
  if (!regionsLayer) return;
  regionsLayer.eachLayer((layer) => {
    const stats = getRegionStats(layer.feature);
    layer.setStyle(regionStyleForHeat(stats));
    const tooltip = layer.getTooltip();
    if (tooltip) {
      tooltip.setContent(formatRegionTooltip(layer.feature.properties.name, stats));
    }
  });
}

function applyCityUpdate(updatedCity) {
  const index = allCities.findIndex((c) => c.name === updatedCity.name);
  if (index !== -1) {
    allCities[index] = updatedCity;
  }
  regionStatsMap = buildRegionStatsMap(allCities);
  renderCities(map.getZoom());
  refreshRegionStyles();
  if (activeCity?.name === updatedCity.name) {
    showCityPopup(updatedCity);
  }
}

function cityVisibleAtZoom(city, zoom) {
  return zoom >= (TIER_MIN_ZOOM[city.tier] ?? 8);
}

function renderCities(zoom) {
  cityLayer.clearLayers();
  cityMarkers.clear();

  for (const city of allCities) {
    if (!cityVisibleAtZoom(city, zoom)) continue;

    const marker = L.marker([city.lat, city.lng], {
      icon: createCityIcon(city),
      title: city.name,
    });

    marker.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      showCityPopup(city);
      map.panTo([city.lat, city.lng], { animate: true });
    });

    marker.bindTooltip(city.name, {
      direction: "top",
      offset: [0, -8],
      opacity: 0.95,
    });

    marker.addTo(cityLayer);
    cityMarkers.set(city.name, marker);
  }
}

function onEachRegion(feature, layer) {
  const name = feature.properties.name;
  const stats = getRegionStats(feature);
  const baseStyle = regionStyleForHeat(stats);

  layer.bindTooltip(formatRegionTooltip(name, stats), {
    sticky: true,
    opacity: 0.95,
  });

  layer.on({
    mouseover: (e) => {
      e.target.setStyle(regionHoverStyle(stats));
    },
    mouseout: (e) => {
      e.target.setStyle(baseStyle);
    },
    click: (e) => {
      L.DomEvent.stopPropagation(e);
      showRegionPopup(name, getRegionStats(feature));
    },
  });
}

function flyToCity(city) {
  const zoom = Math.min(MAX_ZOOM, Math.max(8, TIER_MIN_ZOOM[city.tier] + 2));
  map.flyTo([city.lat, city.lng], zoom, { duration: 0.8 });
  showCityPopup(city);
  searchInput.value = city.name;
  searchResults.hidden = true;
}

function setupMobileLegend() {
  const toggle = document.getElementById("legend-toggle");
  const legend = document.getElementById("map-legend");
  if (!toggle || !legend) return;

  const close = () => {
    legend.classList.remove("legend--open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.textContent = "Легенда";
  };

  toggle.addEventListener("click", () => {
    const open = legend.classList.toggle("legend--open");
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Скрыть" : "Легенда";
  });

  document.addEventListener("click", (e) => {
    if (!legend.classList.contains("legend--open")) return;
    if (e.target.closest(".legend") || e.target.closest(".legend-toggle")) return;
    close();
  });
}

function setupSearch() {
  searchInput.addEventListener("input", () => {
    const query = searchInput.value.trim().toLowerCase();
    searchResults.innerHTML = "";

    if (query.length < 2) {
      searchResults.hidden = true;
      return;
    }

    const matches = allCities
      .filter((c) => c.name.toLowerCase().includes(query))
      .slice(0, 12);

    if (!matches.length) {
      searchResults.hidden = true;
      return;
    }

    for (const city of matches) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.innerHTML = `${city.name} <span class="meta">${city.subject}</span>`;
      btn.addEventListener("click", () => flyToCity(city));
      li.appendChild(btn);
      searchResults.appendChild(li);
    }

    searchResults.hidden = false;
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search")) {
      searchResults.hidden = true;
    }
  });
}

async function loadCities() {
  try {
    const res = await fetch("/api/cities", { cache: "no-store" });
    if (res.ok) {
      return res.json();
    }
  } catch {
    // API unavailable (local static server)
  }

  const res = await fetch("/data/cities.json", { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Не удалось загрузить список городов");
  }
  return res.json();
}

async function loadData() {
  const [regionsRes] = await Promise.all([
    fetch("/data/regions.geojson", { cache: "no-store" }),
  ]);

  allCities = await loadCities();

  if (!regionsRes.ok) {
    throw new Error("Не удалось загрузить данные карты");
  }

  regionStatsMap = buildRegionStatsMap(allCities);
  const regions = await regionsRes.json();

  regionsLayer = L.geoJSON(regions, {
    style: (feature) => regionStyleForHeat(getRegionStats(feature)),
    onEachFeature: onEachRegion,
  }).addTo(map);

  renderCities(map.getZoom());
}

map.on("zoomend", () => {
  const zoom = map.getZoom();
  zoomLevelEl.textContent = String(zoom);
  renderCities(zoom);
});

map.on("click", () => {
  hideCityPopup();
  hideRegionPopup();
});

document
  .querySelector(".city-popup__close")
  .addEventListener("click", hideCityPopup);

document
  .querySelector(".region-popup__close")
  .addEventListener("click", hideRegionPopup);

popupSaveBtn.addEventListener("click", async () => {
  if (!activeCity || !isAdmin()) return;

  popupAdminError.hidden = true;
  popupSaveBtn.disabled = true;

  try {
    const updatedCity = await updateCityStatus(
      activeCity.name,
      popupStatusSelect.value,
      popupCommentInput.value
    );
    applyCityUpdate(updatedCity);
    popupAdminError.hidden = true;
    popupAdminError.textContent = "";
    popupAdminError.className = "popup-admin__success";
    popupAdminError.textContent = "Сохранено";
    popupAdminError.hidden = false;
  } catch (err) {
    popupAdminError.className = "popup-admin__error";
    popupAdminError.textContent = err.message || "Не удалось сохранить";
    popupAdminError.hidden = false;
  } finally {
    popupSaveBtn.disabled = false;
  }
});

onAdminChange((authed) => {
  if (!authed) {
    popupAdmin.hidden = true;
    return;
  }
  if (activeCity && !popup.hidden) {
    showCityPopup(activeCity);
  }
});

setupSearch();
setupMobileLegend();
zoomLevelEl.textContent = String(map.getZoom());

initAdmin()
  .then(() => {
    reportActions = initReports(() => allCities, applyCityUpdate);
    return loadData();
  })
  .catch((err) => {
    console.error(err);
    alert("Ошибка загрузки карты. Проверьте, что данные подготовлены (scripts/prepare_data.py).");
  });
