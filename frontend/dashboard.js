const charts = new Map();

// Same formatting helper as app.js: R$ / grouped-number ticks and tooltips.
function applyFormat(cfg) {
  const currency = cfg._meta && cfg._meta.currency;
  const fmt = (v) =>
    typeof v === "number"
      ? (currency ? "R$ " + v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })
                  : v.toLocaleString("pt-BR", { maximumFractionDigits: 2 }))
      : v;
  cfg.options = cfg.options || {};
  cfg.options.plugins = cfg.options.plugins || {};
  cfg.options.plugins.tooltip = {
    callbacks: {
      label: (ctx) => {
        const name = ctx.dataset.label || ctx.label || "";
        const p = ctx.parsed;
        if (cfg.type === "scatter") {
          const sc = cfg.options.scales || {};
          const xt = (sc.x && sc.x.title && sc.x.title.text) || "x";
          const yt = (sc.y && sc.y.title && sc.y.title.text) || "y";
          // Only show the dot label when it's meaningful (skip long hex ids).
          const raw = ctx.raw || {};
          const tag = raw.label && !/^[0-9a-f]{16,}$/i.test(raw.label)
            ? raw.label + " — " : "";
          return `${tag}${xt}: ${fmt(p.x)}, ${yt}: ${fmt(p.y)}`;
        }
        const val = p && typeof p === "object"
          ? (cfg.options.indexAxis === "y" ? p.x : p.y) : p;
        return `${name}: ${fmt(val)}`;
      },
    },
  };
  if (cfg.type !== "doughnut") {
    const valueAxis = cfg.options.indexAxis === "y" ? "x" : "y";
    cfg.options.scales = cfg.options.scales || {};
    for (const ax of [valueAxis, "y1"]) {
      if (ax === "y1" && !cfg.options.scales.y1) continue;
      cfg.options.scales[ax] = cfg.options.scales[ax] || {};
      cfg.options.scales[ax].ticks = { callback: (v) => fmt(v) };
    }
  }
  return cfg;
}

function renderPin(pin, container) {
  const tpl = document.getElementById("pin-template").content.cloneNode(true);
  const section = tpl.querySelector(".pin");
  section.dataset.id = pin.id;
  tpl.querySelector(".pin-title").textContent = pin.title || pin.question;
  tpl.querySelector(".pin-insight").textContent = pin.insight || "";
  tpl.querySelector(".pin-meta").textContent =
    `asked: "${pin.question}" · agent: ${pin.agent_used}` +
    (pin.refreshed_at ? ` · refreshed: ${pin.refreshed_at}` : "");
  const badge = tpl.querySelector(".change-badge");
  if (pin.last_change) {
    badge.hidden = false;
    badge.textContent = pin.last_change.summary;
    badge.className =
      "change-badge " + (pin.last_change.significant ? "significant" : "nochange");
  }
  const canvas = tpl.querySelector("canvas");
  container.appendChild(tpl);
  const cfg = applyFormat(JSON.parse(JSON.stringify(pin.chart.chartjs_config)));
  charts.set(pin.id, new Chart(canvas.getContext("2d"), cfg));

  section.querySelector(".refresh-btn").addEventListener("click", async () => {
    const r = await fetch(`/api/pins/${pin.id}/refresh`, { method: "POST" });
    if (r.ok) load();
  });
  section.querySelector(".delete-btn").addEventListener("click", async () => {
    await fetch(`/api/pins/${pin.id}`, { method: "DELETE" });
    load();
  });
}

async function load() {
  charts.forEach((c) => c.destroy());
  charts.clear();
  const container = document.getElementById("pins");
  container.innerHTML = "";
  const r = await fetch("/api/pins");
  const { pins } = await r.json();
  if (!pins.length) {
    container.innerHTML =
      '<p class="muted">Nothing pinned yet. Ask a question and hit 📌.</p>';
    return;
  }
  pins.forEach((p) => renderPin(p, container));
}

load();
