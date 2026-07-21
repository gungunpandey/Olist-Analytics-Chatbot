let chart = null;
let lastResponse = null;
let selectedOption = "primary";   // which of the two chart options is on screen

const $ = (id) => document.getElementById(id);

// Shared with dashboard.js (same function there): number/currency formatting
// for ticks + tooltips. Currency flag comes from the backend (_meta.currency).
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

function renderChart(option, which) {
  selectedOption = which || "primary";
  if (chart) chart.destroy();
  // Deep-copy: Chart.js mutates its config object.
  const cfg = applyFormat(JSON.parse(JSON.stringify(option.chartjs_config)));
  chart = new Chart($("chart").getContext("2d"), cfg);
  $("justification").textContent = `Chart: ${option.type} — ${option.justification}`;
}

function show(response) {
  lastResponse = response;
  $("result").hidden = true;
  $("refused").hidden = true;
  $("pin-status").textContent = "";

  if (!response.chart) {
    let msg = response.message || "This question cannot be answered from the dataset.";
    // Surface WHY (e.g. "LLM agent unavailable — answered by the fallback").
    const notes = (response.assumptions || []).filter((a) =>
      a.includes("Fallback") || a.includes("fallback"));
    if (notes.length) msg += "  [" + notes.join(" ") + "]";
    $("refused-msg").textContent = msg;
    $("refused").hidden = false;
    return;
  }
  $("insight").textContent = "💡 " + (response.insight || "");
  const ul = $("assumptions");
  ul.innerHTML = "";
  (response.assumptions || []).forEach((a) => {
    const li = document.createElement("li");
    li.textContent = a;
    ul.appendChild(li);
  });
  if (response.status === "partial" && response.message) {
    const li = document.createElement("li");
    li.textContent = "⚠ " + response.message;
    ul.appendChild(li);
  }
  $("toolcalls").textContent = JSON.stringify(response.tool_calls, null, 2);

  const hasAlt = !!response.chart_alternative;
  $("alt-choice").hidden = !hasAlt;
  if (hasAlt) {
    $("use-primary").textContent = `Option A: ${response.chart.type}`;
    $("use-alt").textContent = `Option B: ${response.chart_alternative.type}`;
    $("use-primary").onclick = () => renderChart(response.chart, "primary");
    $("use-alt").onclick = () => renderChart(response.chart_alternative, "alt");
  }
  renderChart(response.chart, "primary");
  $("result").hidden = false;
}

// --- Live progress log (SSE), ProdAI-style ---
function logStep(text, cls) {
  const div = document.createElement("div");
  div.className = "step " + (cls || "");
  div.textContent = text;
  $("status").appendChild(div);
}

function shortParams(params) {
  const p = Object.fromEntries(
    Object.entries(params || {}).filter(([, v]) => v !== null && v !== undefined));
  const s = JSON.stringify(p);
  return s.length > 90 ? s.slice(0, 87) + "…" : s;
}

function handleEvent(ev) {
  if (ev.type === "status") {
    logStep("⚙ " + ev.message);
  } else if (ev.type === "tool_start") {
    logStep(`→ ${ev.tool} ${shortParams(ev.params)}`);
  } else if (ev.type === "tool_end") {
    logStep(ev.ok
      ? `✓ ${ev.tool} ok${ev.rows != null ? ` — ${ev.rows} rows` : ""}`
      : `✗ ${ev.tool} failed — ${ev.error || "error"}`, ev.ok ? "ok" : "bad");
  } else if (ev.type === "result") {
    show(ev.response);
    $("status").innerHTML = "";
  } else if (ev.type === "error") {
    logStep("✗ " + ev.message, "bad");
  }
}

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("ask-btn").disabled = true;
  $("status").innerHTML = "";
  $("result").hidden = true;
  $("refused").hidden = true;
  logStep("⚙ Question sent — waiting for the agent…");
  try {
    const r = await fetch("/api/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: $("question").value }),
    });
    if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (frame.startsWith("data: ")) handleEvent(JSON.parse(frame.slice(6)));
      }
    }
  } catch (err) {
    logStep("✗ Request failed: " + err.message, "bad");
  } finally {
    $("ask-btn").disabled = false;
  }
});

$("pin-btn").addEventListener("click", async () => {
  if (!lastResponse) return;
  // Pin whichever option is currently on screen: swap primary/alternative
  // (and their shapes, so refresh rebuilds the right chart type).
  const payload = JSON.parse(JSON.stringify(lastResponse));
  if (selectedOption === "alt" && payload.chart_alternative) {
    [payload.chart, payload.chart_alternative] =
      [payload.chart_alternative, payload.chart];
    if (payload.alternative_shape) {
      [payload.data_shape, payload.alternative_shape] =
        [payload.alternative_shape, payload.data_shape];
    }
  }
  const r = await fetch("/api/pins", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("pin-status").textContent = r.ok
    ? "Pinned ✓ — see the Dashboard tab"
    : "Pin failed";
});
