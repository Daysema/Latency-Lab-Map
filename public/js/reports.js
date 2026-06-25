import { api, isAdmin, onAdminChange, sendBackupToTelegram } from "./admin.js";

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
  const successScreen = document.getElementById("report-success-screen");
  const successText = document.getElementById("report-success-text");
  const dialogTitle = dialog.querySelector(".report-dialog__title");
  const dialogIntro = dialog.querySelector(".report-dialog__intro");
  const adminReportsDialog = document.getElementById("admin-reports");
  const adminReportsToggle = document.getElementById("admin-reports-toggle");
  const adminReportsList = document.getElementById("admin-reports-list");
  const adminReportsCount = document.getElementById("admin-reports-count");
  const adminBackupBtn = document.getElementById("admin-backup-btn");
  const adminBackupStatus = document.getElementById("admin-backup-status");
  let selectedCity = "";
  let closeTimer = null;

  function resetDialog() {
    if (closeTimer) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
    form.hidden = false;
    if (dialogTitle) dialogTitle.hidden = false;
    if (dialogIntro) dialogIntro.hidden = false;
    successScreen.hidden = true;
    errorEl.hidden = true;
    form.reset();
    selectedCity = "";
    cityInput.value = "";
    cityResults.hidden = true;
  }

  function hide() {
    dialog.hidden = true;
    resetDialog();
  }

  function show() {
    resetDialog();
    dialog.hidden = false;
    cityInput.focus();
  }

  function showSuccess(message) {
    form.hidden = true;
    if (dialogTitle) dialogTitle.hidden = true;
    if (dialogIntro) dialogIntro.hidden = true;
    errorEl.hidden = true;
    successText.textContent = message;
    successScreen.hidden = false;

    closeTimer = setTimeout(() => {
      hide();
    }, 2000);
  }

  function hideAdminReports() {
    adminReportsDialog.hidden = true;
  }

  async function renderAdminReports() {
    adminReportsList.innerHTML = "";
    const data = await loadReports();

    adminReportsCount.textContent = data.length
      ? `Новых сообщений: ${data.length}`
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
      li.className = "admin-reports__item";

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
      msgEl.textContent = report.message || "—";
      li.appendChild(msgEl);

      if (report.contact) {
        const contactEl = document.createElement("p");
        contactEl.className = "admin-reports__contact";
        contactEl.textContent = `Контакт: ${report.contact}`;
        li.appendChild(contactEl);
      }

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

  adminBackupBtn.addEventListener("click", async () => {
    adminBackupStatus.hidden = true;
    adminBackupBtn.disabled = true;
    try {
      const result = await sendBackupToTelegram();
      adminBackupStatus.textContent = result.telegramSent
        ? `Архив ${result.filename} отправлен в Telegram`
        : "Архив создан, но Telegram не ответил";
      adminBackupStatus.hidden = false;
    } catch (err) {
      adminBackupStatus.textContent = err.message || "Не удалось выгрузить";
      adminBackupStatus.hidden = false;
    } finally {
      adminBackupBtn.disabled = false;
    }
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
      showSuccess(
        result.telegramSent
          ? "Спасибо! Сообщение отправлено и передано на проверку."
          : "Спасибо! Сообщение сохранено и передано на проверку."
      );
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
