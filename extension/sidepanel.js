// sidepanel.js — ToS Inspector Side Panel Logic

const API_BASE = "http://localhost:8000";

// ── State ─────────────────────────────────────────────────────────────────────

let currentUrl = null;
let currentTitle = null;
let currentFavicon = null;
let analysisReport = null;
let loadingTimer = null;

// ── DOM References ────────────────────────────────────────────────────────────

const panels = {
  initial: document.getElementById("stateInitial"),
  loading: document.getElementById("stateLoading"),
  results: document.getElementById("stateResults"),
  error:   document.getElementById("stateError"),
};

const els = {
  siteFavicon:    document.getElementById("siteFavicon"),
  siteName:       document.getElementById("siteName"),
  siteUrl:        document.getElementById("siteUrl"),
  analyzeBtn:     document.getElementById("analyzeBtn"),
  loadingFavicon: document.getElementById("loadingFavicon"),
  loadingSiteName:document.getElementById("loadingSiteName"),
  progressFill:   document.getElementById("progressRingFill"),
  resultsFavicon: document.getElementById("resultsFavicon"),
  resultsSiteName:document.getElementById("resultsSiteName"),
  resultsSiteUrl: document.getElementById("resultsSiteUrl"),
  scoreRingFill:  document.getElementById("scoreRingFill"),
  scoreNumber:    document.getElementById("scoreNumber"),
  overallBadge:   document.getElementById("overallBadge"),
  categoriesList: document.getElementById("categoriesList"),
  reanalyzeBtn:   document.getElementById("reanalyzeBtn"),
  copyReportBtn:  document.getElementById("copyReportBtn"),
  analysisMeta:   document.getElementById("analysisMeta"),
  errorMessage:   document.getElementById("errorMessage"),
  tryAgainBtn:    document.getElementById("tryAgainBtn"),
  headerBadge:    document.getElementById("headerBadge"),
};

// ── Show/hide panels ──────────────────────────────────────────────────────────

function showPanel(name) {
  Object.entries(panels).forEach(([key, el]) => {
    el.hidden = key !== name;
  });
}

// ── Severity helpers ──────────────────────────────────────────────────────────

const STATUS_LABELS = {
  green:   "✓ Safe",
  yellow:  "⚠ Caution",
  red:     "✖ Concern",
  blocker: "⛔ Blocker",
};

const STATUS_SCORE_COLORS = {
  green:   "#22c55e",
  yellow:  "#eab308",
  red:     "#ef4444",
  blocker: "#a855f7",
};

function severityClass(status) {
  return `status-${status}`;
}

function dotClass(status) {
  return `dot-${status}`;
}

// ── Tab info ──────────────────────────────────────────────────────────────────

function getSiteName(url, title) {
  try {
    const hostname = new URL(url).hostname.replace(/^www\./, "");
    return hostname || title || "Unknown Site";
  } catch {
    return title || "Unknown Site";
  }
}

function updateSiteInfo(url, title, favIconUrl) {
  currentUrl = url;
  currentTitle = title;
  currentFavicon = favIconUrl || "";

  const siteName = getSiteName(url, title);

  // Favicon
  [els.siteFavicon, els.loadingFavicon, els.resultsFavicon].forEach(img => {
    img.src = favIconUrl || `https://www.google.com/s2/favicons?domain=${url}&sz=32`;
    img.onerror = () => { img.src = ""; img.style.display = "none"; };
  });

  els.siteName.textContent = siteName;
  try {
    els.siteUrl.textContent = new URL(url).hostname;
  } catch {
    els.siteUrl.textContent = url;
  }
  els.loadingSiteName.textContent = siteName;
}

// ── Loading animation ─────────────────────────────────────────────────────────

const STEPS = ["step0", "step1", "step2", "step3"];
const STEP_DURATIONS = [3000, 4000, 12000, 4000]; // ms per step (approx)

function startLoadingAnimation() {
  let stepIndex = 0;
  const circumference = 263.9;

  function activateStep(i) {
    STEPS.forEach((id, idx) => {
      const el = document.getElementById(id);
      if (idx < i) {
        el.className = "loading-step done";
      } else if (idx === i) {
        el.className = "loading-step active";
      } else {
        el.className = "loading-step";
      }
    });

    // Update progress ring
    const progress = (i + 1) / STEPS.length;
    const offset = circumference * (1 - progress * 0.9);
    els.progressFill.style.strokeDashoffset = offset;
  }

  activateStep(0);

  loadingTimer = setInterval(() => {
    stepIndex = Math.min(stepIndex + 1, STEPS.length - 1);
    activateStep(stepIndex);
    if (stepIndex >= STEPS.length - 1) clearInterval(loadingTimer);
  }, STEP_DURATIONS[stepIndex] || 5000);
}

function stopLoadingAnimation() {
  clearInterval(loadingTimer);
  // Complete the ring
  els.progressFill.style.strokeDashoffset = "0";
  STEPS.forEach(id => {
    document.getElementById(id).className = "loading-step done";
  });
}

// ── Score ring ────────────────────────────────────────────────────────────────

function animateScore(score, status) {
  const circumference = 226.2;
  const color = STATUS_SCORE_COLORS[status] || "#818cf8";

  // Set color
  els.scoreRingFill.style.stroke = color;

  // Animate offset: start full (all hidden) → reveal score
  els.scoreRingFill.style.strokeDashoffset = String(circumference);

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const offset = circumference * (1 - score / 100);
      els.scoreRingFill.style.strokeDashoffset = String(offset);
    });
  });

  // Count up number
  let current = 0;
  const target = score;
  const duration = 900;
  const step = target / (duration / 16);
  const interval = setInterval(() => {
    current = Math.min(current + step, target);
    els.scoreNumber.textContent = Math.round(current);
    els.scoreNumber.style.color = color;
    if (current >= target) clearInterval(interval);
  }, 16);
}

// ── Render results ────────────────────────────────────────────────────────────

function renderResults(report) {
  analysisReport = report;

  const siteName = report.site_name || getSiteName(currentUrl, currentTitle);
  els.resultsSiteName.textContent = siteName;
  try {
    els.resultsSiteUrl.textContent = new URL(currentUrl).hostname;
  } catch {
    els.resultsSiteUrl.textContent = currentUrl || "";
  }

  // Overall badge
  const status = report.overall_status;
  els.overallBadge.className = `overall-badge ${severityClass(status)}`;
  els.overallBadge.innerHTML = `
    <span style="font-size:13px">${statusEmoji(status)}</span>
    ${STATUS_LABELS[status] || status}
    &nbsp;&mdash;&nbsp;Overall Risk Score: <strong>${report.overall_score}/100</strong>
  `;

  // Header badge
  els.headerBadge.className = `header-badge ${severityClass(status)}`;
  els.headerBadge.textContent = STATUS_LABELS[status] || status;

  // Score ring
  animateScore(report.overall_score, status);

  // Categories
  els.categoriesList.innerHTML = "";
  report.categories.forEach((cat, i) => {
    els.categoriesList.appendChild(buildCategoryRow(cat, i));
  });

  // Meta
  els.analysisMeta.textContent =
    `Analyzed in ${report.analysis_time_seconds}s · ${report.categories.length} categories reviewed`;

  showPanel("results");
}

function statusEmoji(status) {
  return { green: "✓", yellow: "⚠", red: "✖", blocker: "⛔" }[status] || "";
}

function buildCategoryRow(cat, index) {
  const row = document.createElement("div");
  row.className = `category-row border-${cat.status}`;
  row.id = `cat-row-${index}`;

  const hasEvidence = cat.evidence && cat.evidence.length > 0;

  const evidenceHtml = hasEvidence
    ? `<div class="evidence-label">Evidence</div>
       <div class="evidence-list">
         ${cat.evidence.map(ev =>
           `<div class="evidence-item">"${escHtml(ev)}"</div>`
         ).join("")}
       </div>`
    : "";

  row.innerHTML = `
    <div class="category-header" role="button" aria-expanded="false" aria-controls="cat-body-${index}">
      <span class="category-dot ${dotClass(cat.status)}"></span>
      <span class="category-name">${escHtml(cat.category)}</span>
      <span class="status-pill ${severityClass(cat.status)}">${cat.status.toUpperCase()}</span>
      <svg class="category-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="category-body" id="cat-body-${index}">
      <div class="category-content">
        <p class="category-details">${escHtml(cat.details)}</p>
        ${evidenceHtml}
      </div>
    </div>
  `;

  // Toggle expand/collapse
  const header = row.querySelector(".category-header");
  header.addEventListener("click", () => {
    const isOpen = row.classList.toggle("open");
    header.setAttribute("aria-expanded", String(isOpen));
  });

  return row;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Copy report ───────────────────────────────────────────────────────────────

function buildPlainTextReport(report) {
  const lines = [
    `ToS Inspector Report`,
    `${"=".repeat(40)}`,
    `Site:           ${report.site_name}`,
    `Overall Score:  ${report.overall_score}/100`,
    `Overall Status: ${report.overall_status.toUpperCase()}`,
    `Analyzed in:    ${report.analysis_time_seconds}s`,
    "",
    `CATEGORY FINDINGS`,
    `${"-".repeat(40)}`,
  ];

  report.categories.forEach(cat => {
    lines.push(`\n[${cat.status.toUpperCase()}] ${cat.category}`);
    lines.push(`  ${cat.headline}`);
    lines.push(`  ${cat.details}`);
    if (cat.evidence && cat.evidence.length > 0) {
      lines.push("  Evidence:");
      cat.evidence.forEach(ev => lines.push(`    • "${ev}"`));
    }
  });

  lines.push(`\n${"=".repeat(40)}`);
  lines.push(`Generated by ToS Inspector`);

  return lines.join("\n");
}

function copyReport() {
  if (!analysisReport) return;
  const text = buildPlainTextReport(analysisReport);

  navigator.clipboard.writeText(text).then(() => {
    const orig = els.copyReportBtn.innerHTML;
    els.copyReportBtn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M20 6L9 17l-5-5" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      Copied!
    `;
    els.copyReportBtn.style.color = "#22c55e";
    setTimeout(() => {
      els.copyReportBtn.innerHTML = orig;
      els.copyReportBtn.style.color = "";
    }, 2000);
  }).catch(err => console.error("Copy failed:", err));
}

// ── Run analysis ──────────────────────────────────────────────────────────────

async function runAnalysis(forceRefresh = false) {
  if (!currentUrl) return;

  showPanel("loading");
  startLoadingAnimation();

  try {
    const response = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: currentUrl, force_refresh: forceRefresh }),
    });

    stopLoadingAnimation();

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      const msg = errData?.detail?.error || `Server error ${response.status}`;
      showError(msg);
      return;
    }

    const report = await response.json();
    renderResults(report);
  } catch (err) {
    stopLoadingAnimation();
    showError(`Could not reach the ToS Inspector backend.\nMake sure it is running on ${API_BASE}`);
    console.error("Analysis error:", err);
  }
}

function showError(msg) {
  els.errorMessage.textContent = msg;
  showPanel("error");
}

// ── New site detection removed ─────────────────────────────────────────────────────

// ── Event Listeners ───────────────────────────────────────────────────────────

els.analyzeBtn.addEventListener("click", () => runAnalysis(false));
els.reanalyzeBtn.addEventListener("click", () => runAnalysis(true));
els.tryAgainBtn.addEventListener("click", () => runAnalysis(false));
els.copyReportBtn.addEventListener("click", copyReport);

// ── Chrome message listeners ──────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "TAB_URL" || message.type === "TAB_UPDATED") {
    updateSiteInfo(message.url, message.title, message.favIconUrl);
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  showPanel("initial");

  // Request current tab info from background service worker
  try {
    const tabInfo = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "GET_CURRENT_TAB" }, (response) => {
        resolve(response || {});
      });
    });

    if (tabInfo.url) {
      updateSiteInfo(tabInfo.url, tabInfo.title, tabInfo.favIconUrl);
    } else {
      els.siteName.textContent = "No active tab detected";
    }
  } catch (err) {
    console.error("Failed to get current tab:", err);
    els.siteName.textContent = "Unable to detect tab";
  }
}

init();
