const cardsEl = document.getElementById("cards");
const template = document.getElementById("card-template");
const refreshBtn = document.getElementById("refresh-btn");
const categorySelect = document.getElementById("category-select");
const statusEl = document.getElementById("status-text");
const statsEl = document.getElementById("stats-line");

let countdownTimer = null;

function formatCountdown(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m} мин ${r} с` : `${r} с`;
}

function startCountdown(seconds) {
  clearInterval(countdownTimer);
  let remaining = seconds;
  refreshBtn.disabled = true;

  const tick = () => {
    if (remaining <= 0) {
      clearInterval(countdownTimer);
      refreshBtn.disabled = false;
      statusEl.textContent = "Готово к обновлению";
      loadListings();
      return;
    }
    statusEl.textContent = `Можно обновить через ${formatCountdown(remaining)}`;
    remaining -= 1;
  };

  tick();
  countdownTimer = setInterval(tick, 1000);
}

function renderCard(listing) {
  const node = template.content.cloneNode(true);
  const card = node.querySelector(".card");

  if (listing.is_new) card.classList.add("card--new");

  node.querySelector(".card__title").textContent = listing.title || "Без названия";
  node.querySelector(".card__description").textContent = listing.description || "";

  node.querySelector(".card__budget").textContent = listing.budget
    ? `Бюджет: ${listing.budget}`
    : "Бюджет не указан";

  const timeLeftEl = node.querySelector(".card__time-left");
  if (listing.time_left) {
    timeLeftEl.textContent = `Осталось: ${listing.time_left}`;
  } else {
    timeLeftEl.remove();
  }

  node.querySelector(".card__responses").textContent = `Откликов: ${listing.responses_count ?? 0}`;
  node.querySelector(".card__author").textContent = listing.author
    ? `Заказчик: ${listing.author}`
    : "";

  const aiNoteEl = node.querySelector(".card__ai-note");
  if (listing.ai_reason) {
    aiNoteEl.textContent = `Одобрено Gemini: ${listing.ai_reason}`;
  } else {
    aiNoteEl.remove();
  }

  const link = node.querySelector(".card__link");
  link.href = listing.url;

  return node;
}

function renderListings(listings) {
  cardsEl.innerHTML = "";

  if (!listings || listings.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Заказов пока нет — попробуйте обновить позже.";
    cardsEl.appendChild(empty);
    return;
  }

  for (const listing of listings) {
    cardsEl.appendChild(renderCard(listing));
  }
}

function showError(message) {
  cardsEl.innerHTML = "";
  const err = document.createElement("p");
  err.className = "error-state";
  err.textContent = message || "Неизвестная ошибка";
  cardsEl.appendChild(err);
}

async function loadCategories() {
  try {
    const res = await fetch("/api/categories");
    const categories = await res.json();
    for (const cat of categories) {
      const opt = document.createElement("option");
      opt.value = String(cat.id);
      opt.textContent = cat.name;
      categorySelect.appendChild(opt);
    }
  } catch (err) {
    // Список категорий — необязательное улучшение; при сбое остаётся пункт "Все категории".
  }
}

async function loadListings() {
  const category = categorySelect.value;
  const categoryLabel = category
    ? categorySelect.options[categorySelect.selectedIndex].textContent
    : "всех категориях";

  refreshBtn.disabled = true;
  categorySelect.disabled = true;
  statusEl.textContent = "Парсим биржу и проверяем новые заказы через Gemini (может занять пару минут)…";

  try {
    const url = category
      ? `/api/listings?pages=1&category=${encodeURIComponent(category)}`
      : "/api/listings?pages=1";
    const res = await fetch(url);
    const payload = await res.json();
    categorySelect.disabled = false;

    if (payload.status === "error") {
      statusEl.textContent = "Ошибка — см. подробности ниже";
      showError(payload.message);
      refreshBtn.disabled = false;
      return;
    }

    renderListings(payload.listings);

    if (payload.total_on_site) {
      const checked = payload.checked_count ?? payload.listings.length;
      statsEl.textContent = `Одобрено Gemini ${payload.listings.length} из ${checked} проверенных заказов в ${category ? `категории «${categoryLabel}»` : categoryLabel} · всего на бирже сейчас ${payload.total_on_site}`;
    }

    startCountdown(payload.retry_after ?? 90);
  } catch (err) {
    categorySelect.disabled = false;
    statusEl.textContent = "Не удалось связаться с локальным сервером";
    refreshBtn.disabled = false;
  }
}

refreshBtn.addEventListener("click", () => {
  if (!refreshBtn.disabled) loadListings();
});

categorySelect.addEventListener("change", () => {
  clearInterval(countdownTimer);
  loadListings();
});

loadCategories();
loadListings();
