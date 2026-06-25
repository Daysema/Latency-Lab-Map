import { initAdmin, isAdmin, onAdminChange, updateCityStatus } from "./admin.js";

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

const STATUS_PRIORITY = {
  unknown: 0,
  ok: 1,
  temp_rare: 2,
  temp_frequent: 3,
  permanent: 4,
};

/** City subject names → region names in GeoJSON */
const SUBJECT_ALIASES = {
  Алтай: "Республика Алтай",
  Башкортостан: "Республика Башкортостан",
  Коми: "Республика Коми",
  Крым: "Автономная Республика Крым",
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

const RUSSIA_BOUNDS = [
  [41.0, 19.0],
  [82.0, 180.0],
];

const map = L.map("map", {
  minZoom: MIN_ZOOM,
  maxZoom: MAX_ZOOM,
  maxBounds: RUSSIA_BOUNDS,
  maxBoundsViscosity: 0.85,
  zoomControl: true,
}).setView([61.5, 96.0], 3);

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
const popupSaveBtn = document.getElementById("popup-save");
const popupAdminError = document.getElementById("popup-admin-error");

let allCities = [];
let cityMarkers = new Map();
let regionStatusMap = {};
let regionsLayer = null;
let activeCity = null;

function cityStatus(city) {
  return city.status || "unknown";
}

function normalizeSubject(subject) {
  return SUBJECT_ALIASES[subject] || subject;
}

function buildRegionStatusMap(cities) {
  const map = {};
  for (const city of cities) {
    const region = normalizeSubject(city.subject || "");
    if (!region) continue;
    const status = cityStatus(city);
    const prev = map[region];
    if (
      prev === undefined ||
      STATUS_PRIORITY[status] > STATUS_PRIORITY[prev]
    ) {
      map[region] = status;
    }
  }
  return map;
}

function getRegionStatus(feature) {
  const name = feature.properties.name;
  return regionStatusMap[name] || feature.properties.status || "unknown";
}

function regionStyleForStatus(status) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return {
    fillColor: color,
    fillOpacity: 0.1,
    color,
    weight: 1.5,
    opacity: 0.8,
  };
}

function regionHoverStyle(status) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return {
    fillColor: color,
    fillOpacity: 0.3,
    color,
    weight: 2.5,
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

  if (isAdmin()) {
    popupAdmin.hidden = false;
    popupStatusSelect.value = cityStatus(city);
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

function refreshRegionStyles() {
  if (!regionsLayer) return;
  regionsLayer.eachLayer((layer) => {
    const status = getRegionStatus(layer.feature);
    layer.setStyle(regionStyleForStatus(status));
    const tooltip = layer.getTooltip();
    if (tooltip) {
      tooltip.setContent(
        `${layer.feature.properties.name}<br><span style="opacity:0.85">${STATUS_LABELS[status]}</span>`
      );
    }
  });
}

function applyCityUpdate(updatedCity) {
  const index = allCities.findIndex((c) => c.name === updatedCity.name);
  if (index !== -1) {
    allCities[index] = updatedCity;
  }
  regionStatusMap = buildRegionStatusMap(allCities);
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
  const status = getRegionStatus(feature);
  const baseStyle = regionStyleForStatus(status);

  layer.bindTooltip(
    `${name}<br><span style="opacity:0.85">${STATUS_LABELS[status]}</span>`,
    { sticky: true, opacity: 0.95 }
  );

  layer.on({
    mouseover: (e) => {
      e.target.setStyle(regionHoverStyle(status));
    },
    mouseout: (e) => {
      e.target.setStyle(baseStyle);
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

  regionStatusMap = buildRegionStatusMap(allCities);
  const regions = await regionsRes.json();

  regionsLayer = L.geoJSON(regions, {
    style: (feature) => regionStyleForStatus(getRegionStatus(feature)),
    onEachFeature: onEachRegion,
  }).addTo(map);

  renderCities(map.getZoom());
}

map.on("zoomend", () => {
  const zoom = map.getZoom();
  zoomLevelEl.textContent = String(zoom);
  renderCities(zoom);
});

map.on("click", hideCityPopup);

document
  .querySelector(".city-popup__close")
  .addEventListener("click", hideCityPopup);

popupSaveBtn.addEventListener("click", async () => {
  if (!activeCity || !isAdmin()) return;

  popupAdminError.hidden = true;
  popupSaveBtn.disabled = true;

  try {
    const updatedCity = await updateCityStatus(
      activeCity.name,
      popupStatusSelect.value
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
zoomLevelEl.textContent = String(map.getZoom());

initAdmin().then(() => loadData()).catch((err) => {
  console.error(err);
  alert("Ошибка загрузки карты. Проверьте, что данные подготовлены (scripts/prepare_data.py).");
});
