let authenticated = false;
let adminConfigured = false;
const listeners = new Set();

export async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const message = data?.detail || "Ошибка запроса";
    throw new Error(
      typeof message === "string" ? message : JSON.stringify(message)
    );
  }

  return data;
}

export function isAdmin() {
  return authenticated;
}

export function onAdminChange(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function notify() {
  for (const callback of listeners) {
    callback(authenticated);
  }
}

function setAuthenticated(value) {
  authenticated = value;
  notify();
}

export async function checkAuth() {
  try {
    const data = await api("/api/auth/me");
    adminConfigured = data.adminConfigured;
    setAuthenticated(Boolean(data.authenticated));
    return data;
  } catch {
    setAuthenticated(false);
    return { authenticated: false, adminConfigured: false };
  }
}

export async function login(password) {
  await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  setAuthenticated(true);
}

export async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  setAuthenticated(false);
}

export async function updateCityStatus(name, status) {
  const data = await api("/api/cities", {
    method: "PATCH",
    body: JSON.stringify({ name, status }),
  });
  return data.city;
}

export function initAdmin() {
  const toggleBtn = document.getElementById("admin-toggle");
  const loginDialog = document.getElementById("admin-login");
  const loginForm = document.getElementById("admin-login-form");
  const loginError = document.getElementById("admin-login-error");
  const passwordInput = document.getElementById("admin-password");

  function showLogin() {
    loginDialog.hidden = false;
    loginError.hidden = true;
    passwordInput.value = "";
    passwordInput.focus();
  }

  function hideLogin() {
    loginDialog.hidden = true;
  }

  function updateToggle() {
    if (authenticated) {
      toggleBtn.textContent = "✏️";
      toggleBtn.title = "Режим редактирования (выйти)";
      toggleBtn.setAttribute("aria-label", "Режим редактирования, выйти");
      toggleBtn.classList.add("admin-toggle--active");
    } else {
      toggleBtn.textContent = "🔒";
      toggleBtn.title = "Вход администратора";
      toggleBtn.setAttribute("aria-label", "Вход администратора");
      toggleBtn.classList.remove("admin-toggle--active");
    }
  }

  onAdminChange(updateToggle);

  toggleBtn.addEventListener("click", async () => {
    if (authenticated) {
      await logout();
      return;
    }
    if (!adminConfigured) {
      alert(
        "Админ-доступ не настроен. Задайте ADMIN_PASSWORD в файле .env на сервере."
      );
      return;
    }
    showLogin();
  });

  loginDialog.querySelector(".admin-login__close").addEventListener("click", hideLogin);

  loginDialog.addEventListener("click", (e) => {
    if (e.target === loginDialog) hideLogin();
  });

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.hidden = true;
    try {
      await login(passwordInput.value);
      hideLogin();
    } catch (err) {
      loginError.textContent = err.message || "Неверный пароль";
      loginError.hidden = false;
    }
  });

  return checkAuth();
}
