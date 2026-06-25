import { api, isAdmin } from "./admin.js";

export function initReports(allCitiesGetter) {
  const dialog = document.getElementById("report-dialog");
  const form = document.getElementById("report-form");
  const openBtn = document.getElementById("report-open");
  const cityInput = document.getElementById("report-city");
  const cityResults = document.getElementById("report-city-results");
  const errorEl = document.getElementById("report-error");
  const successEl = document.getElementById("report-success");
  let selectedCity = "";

  function hide() {
    dialog.hidden = true;
    errorEl.hidden = true;
    successEl.hidden = true;
  }

  function show() {
    dialog.hidden = false;
    form.reset();
    selectedCity = "";
    cityInput.value = "";
    cityResults.hidden = true;
    errorEl.hidden = true;
    successEl.hidden = true;
    cityInput.focus();
  }

  openBtn.addEventListener("click", show);
  dialog.querySelector(".report-dialog__close").addEventListener("click", hide);
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) hide();
  });

  cityInput.addEventListener("input", () => {
    const query = cityInput.value.trim().toLowerCase();
    cityResults.innerHTML = "";
    selectedCity = "";

    if (query.length < 2) {
      cityResults.hidden = true;
      return;
    }

    const matches = allCitiesGetter()
      .filter((c) => c.name.toLowerCase().includes(query))
      .slice(0, 10);

    if (!matches.length) {
      cityResults.hidden = true;
      return;
    }

    for (const city of matches) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = `${city.name} (${city.subject})`;
      btn.addEventListener("click", () => {
        selectedCity = city.name;
        cityInput.value = city.name;
        cityResults.hidden = true;
      });
      li.appendChild(btn);
      cityResults.appendChild(li);
    }

    cityResults.hidden = false;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.hidden = true;
    successEl.hidden = true;

    const city = selectedCity || cityInput.value.trim();
    const message = document.getElementById("report-message").value.trim();
    const status = document.getElementById("report-status").value;
    const contact = document.getElementById("report-contact").value.trim();

    if (!city) {
      errorEl.textContent = "Укажите город";
      errorEl.hidden = false;
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    try {
      await api("/api/reports", {
        method: "POST",
        body: JSON.stringify({
          city,
          status: status || null,
          message,
          contact: contact || null,
        }),
      });
      successEl.textContent =
        "Спасибо! Сообщение отправлено и добавлено в очередь на проверку.";
      successEl.hidden = false;
      form.reset();
      selectedCity = "";
    } catch (err) {
      errorEl.textContent = err.message || "Не удалось отправить";
      errorEl.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });

  return { showReportForCity(cityName) {
    show();
    selectedCity = cityName;
    cityInput.value = cityName;
  }};
}

export async function loadReports() {
  if (!isAdmin()) return [];
  try {
    const data = await api("/api/reports");
    return data.reports || [];
  } catch {
    return [];
  }
}
