const TIER_LABELS = {
  capital: "Столица",
  megacity: "Город-миллионник",
  large: "Крупный город",
  regional: "Областной / региональный центр",
  small: "Малый город",
  town: "Населённый пункт",
};

const TIER_COLORS = {
  capital: "#f59e0b",
  megacity: "#ef4444",
  large: "#f97316",
  regional: "#3b82f6",
  small: "#22c55e",
  town: "#94a3b8",
};

const TIER_RADIUS = {
  capital: 9,
  megacity: 8,
  large: 7,
  regional: 6,
  small: 5,
  town: 4,
};

/** Minimum zoom to show each city tier */
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

let allCities = [];
let cityMarkers = new Map();

function formatPopulation(n) {
  return new Intl.NumberFormat("ru-RU").format(n) + " чел.";
}

function createCityIcon(tier) {
  const radius = TIER_RADIUS[tier] || 5;
  const color = TIER_COLORS[tier] || TIER_COLORS.town;

  return L.divIcon({
    className: `city-marker city-marker--${tier}`,
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
  document.getElementById("popup-name").textContent = city.name;
  document.getElementById("popup-subject").textContent = city.subject || "—";
  document.getElementById("popup-population").textContent = formatPopulation(
    city.population
  );
  document.getElementById("popup-tier").textContent =
    TIER_LABELS[city.tier] || city.tier;
  popup.hidden = false;
}

function hideCityPopup() {
  popup.hidden = true;
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
      icon: createCityIcon(city.tier),
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

function regionStyle() {
  return {
    fillColor: "#3b82f6",
    fillOpacity: 0.06,
    color: "#93c5fd",
    weight: 1,
    opacity: 0.55,
  };
}

function onEachRegion(feature, layer) {
  const name = feature.properties.name;
  layer.bindTooltip(name, { sticky: true, opacity: 0.9 });

  layer.on({
    mouseover: (e) => {
      e.target.setStyle({
        fillOpacity: 0.18,
        weight: 1.5,
        opacity: 0.85,
      });
    },
    mouseout: (e) => {
      e.target.setStyle(regionStyle());
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

async function loadData() {
  const [citiesRes, regionsRes] = await Promise.all([
    fetch("data/cities.json"),
    fetch("data/regions.geojson"),
  ]);

  if (!citiesRes.ok || !regionsRes.ok) {
    throw new Error("Не удалось загрузить данные карты");
  }

  allCities = await citiesRes.json();
  const regions = await regionsRes.json();

  L.geoJSON(regions, {
    style: regionStyle,
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

setupSearch();
zoomLevelEl.textContent = String(map.getZoom());

loadData().catch((err) => {
  console.error(err);
  alert("Ошибка загрузки карты. Проверьте, что данные подготовлены (scripts/prepare_data.py).");
});
