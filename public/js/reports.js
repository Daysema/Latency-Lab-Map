import { api, isAdmin, onAdminChange } from "./admin.js";

const STATUS_LABELS = {
  unknown: "Нет информации",
  ok: "Нет ограничений",
  temp_rare: "Временные (редкие)",
  temp_frequent: "Временные (частые)",
  permanent: "Постоянные ограничения",
};

function formatDate(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function initReports(allCitiesGetter, onCityUpdated) {
  const dialog = document.getElementById("report-dialog");
  const form = document.getElementById("report-form");
  const openBtn = document.getElementById("report-open");
  const cityInput = document.getElementById("report-city");
  const cityResults = document.getElementById("report-city-results");
  const errorEl = document.getElementById("report-error");
  const successEl = document.getElementById("report-success");
  const adminReportsDialog = document.getElementById("admin-reports");
  const adminReportsToggle = document.getElementById("admin-reports-toggle");
  const adminReportsList = document.getElementById("admin-reports-list");
  const adminReportsCount = document.getElementById("admin-reports-count");
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

  function hideAdminReports() {
    adminReportsDialog.hidden = true;
  }

  async function renderAdminReports() {
    adminReportsList.innerHTML = "";
    const data = await loadReports();
    const pending = data.filter((r) => !r.reviewed);

    adminReportsCount.textContent = pending.length
      ? `Новых сообщений: ${pending.length}`
      : "Новых сообщений нет";

    if (!data.length) {
      const li = document.createElement("li");
      li.className = "admin-reports__empty";
      li.textContent = "Очередь пуста";
      adminReportsList.appendChild(li);
      return;
    }

    for (const report of data) {
      const li = document.createElement("li");
      li.className = report.reviewed
        ? "admin-reports__item admin-reports__item--done"
        : "admin-reports__item";

      const statusText = report.status
        ? STATUS_LABELS[report.status] || report.status
        : "Статус не указан";

      const head = document.createElement("div");
      head.className = "admin-reports__meta";
      const cityEl = document.createElement("strong");
      cityEl.textContent = report.city;
      const dateEl = document.createElement("span");
      dateEl.textContent = formatDate(report.createdAt);
      head.appendChild(cityEl);
      head.appendChild(dateEl);
      li.appendChild(head);

      const statusEl = document.createElement("div");
      statusEl.className = "admin-reports__status";
      statusEl.textContent = statusText;
      li.appendChild(statusEl);

      const msgEl = document.createElement("p");
      msgEl.className = "admin-reports__message";
      msgEl.textContent = report.message;
      li.appendChild(msgEl);

      if (report.contact) {
        const contactEl = document.createElement("p");
        contactEl.className = "admin-reports__contact";
        contactEl.textContent = `Контакт: ${report.contact}`;
        li.appendChild(contactEl);
      }

      if (!report.reviewed) {
        const actions = document.createElement("div");
        actions.className = "admin-reports__actions";

        if (report.status) {
          const applyBtn = document.createElement("button");
          applyBtn.type = "button";
          applyBtn.textContent = "Применить на карту";
          applyBtn.addEventListener("click", async () => {
            applyBtn.disabled = true;
            try {
              const result = await api(`/api/reports/${report.id}`, {
                method: "PATCH",
                body: JSON.stringify({ apply: true }),
              });
              if (result.city && onCityUpdated) {
                onCityUpdated(result.city);
              }
              await renderAdminReports();
            } catch (err) {
              alert(err.message || "Не удалось применить");
              applyBtn.disabled = false;
            }
          });
          actions.appendChild(applyBtn);
        }

        const dismissBtn = document.createElement("button");
        dismissBtn.type = "button";
        dismissBtn.className = "admin-reports__dismiss";
        dismissBtn.textContent = "Отметить просмотренным";
        dismissBtn.addEventListener("click", async () => {
          dismissBtn.disabled = true;
          try {
            await api(`/api/reports/${report.id}`, {
              method: "PATCH",
              body: JSON.stringify({ apply: false }),
            });
            await renderAdminReports();
          } catch (err) {
            alert(err.message || "Не удалось обновить");
            dismissBtn.disabled = false;
          }
        });
        actions.appendChild(dismissBtn);
        li.appendChild(actions);
      }

      adminReportsList.appendChild(li);
    }
  }

  async function showAdminReports() {
    adminReportsDialog.hidden = false;
    await renderAdminReports();
  }

  openBtn.addEventListener("click", show);
  dialog.querySelector(".report-dialog__close").addEventListener("click", hide);
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) hide();
  });

  adminReportsToggle.addEventListener("click", showAdminReports);
  adminReportsDialog
    .querySelector(".admin-reports__close")
    .addEventListener("click", hideAdminReports);
  adminReportsDialog.addEventListener("click", (e) => {
    if (e.target === adminReportsDialog) hideAdminReports();
  });

  onAdminChange((authed) => {
    adminReportsToggle.hidden = !authed;
    if (!authed) hideAdminReports();
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
      const result = await api("/api/reports", {
        method: "POST",
        body: JSON.stringify({
          city,
          status: status || null,
          message,
          contact: contact || null,
        }),
      });
      successEl.textContent = result.telegramSent
        ? "Спасибо! Сообщение сохранено и отправлено на проверку."
        : "Спасибо! Сообщение сохранено и добавлено в очередь на проверку.";
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

  return {
    showReportForCity(cityName) {
      show();
      selectedCity = cityName;
      cityInput.value = cityName;
    },
  };
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
