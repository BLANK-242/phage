"use strict";
/* PHAGE dashboard — hand-written SVG, no framework, no build step, no CDN.
   Nothing here recomputes an evaluation figure: stored values are rendered as
   stored. The only arithmetic is chart geometry. */

const THRESHOLD = 0.59;
const SVG_NS = "http://www.w3.org/2000/svg";

const el = (tag, attrs = {}, text) => {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
};
const h = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const errBox = (msg) => h("div", "error", msg);

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const want = btn.dataset.view;
    document.getElementById("view-eval").classList.toggle("hidden", want !== "eval");
    document.getElementById("view-trace").classList.toggle("hidden", want !== "trace");
    if (want === "trace") loadSessions();
  });
});

/* ---------------- ROC ---------------- */
/* Recognition is `distance < threshold`, so a LOWER distance is a stronger
   positive prediction. Sweeping the threshold upward walks the curve. */
function rocPoints(pos, neg) {
  const cuts = [...new Set([...pos, ...neg])].sort((a, b) => a - b);
  const pts = [[0, 0]];
  for (const c of cuts) {
    const tp = pos.filter((d) => d <= c).length;
    const fp = neg.filter((d) => d <= c).length;
    pts.push([fp / neg.length, tp / pos.length]);
  }
  pts.push([1, 1]);
  return pts;
}

function drawRoc(loao) {
  const host = document.getElementById("roc");
  host.textContent = "";
  if (loao.error) { host.appendChild(errBox(loao.error)); return; }

  const pos = loao.pooled_positives_sorted || [];
  const neg = loao.pooled_negatives_sorted || [];
  if (!pos.length || !neg.length) {
    host.appendChild(errBox("pooled distance arrays missing from loao_eval_result.json"));
    return;
  }

  const W = 420, H = 360, M = { t: 14, r: 16, b: 46, l: 54 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const X = (v) => M.l + v * iw;
  const Y = (v) => M.t + (1 - v) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H,
                          role: "img", "aria-label": "ROC curve" });

  for (let i = 0; i <= 5; i++) {
    const t = i / 5;
    svg.appendChild(el("line", { x1: X(t), y1: Y(0), x2: X(t), y2: Y(1),
                                 stroke: "#26415e", "stroke-width": 1 }));
    svg.appendChild(el("line", { x1: X(0), y1: Y(t), x2: X(1), y2: Y(t),
                                 stroke: "#26415e", "stroke-width": 1 }));
    svg.appendChild(el("text", { x: X(t), y: Y(0) + 20, "text-anchor": "middle",
                                 class: "axis" , fill: "#9FB3C8", "font-size": 13 }, t.toFixed(1)));
    svg.appendChild(el("text", { x: X(0) - 10, y: Y(t) + 4, "text-anchor": "end",
                                 fill: "#9FB3C8", "font-size": 13 }, t.toFixed(1)));
  }

  svg.appendChild(el("line", { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1),
                               stroke: "#9FB3C8", "stroke-width": 1.5,
                               "stroke-dasharray": "5 5" }));

  const pts = rocPoints(pos, neg);
  svg.appendChild(el("polyline", {
    points: pts.map(([x, y]) => `${X(x)},${Y(y)}`).join(" "),
    fill: "none", stroke: "#00B4D8", "stroke-width": 2.5,
    "stroke-linejoin": "round",
  }));

  const at = (loao["fpr_at_tpr_1.00"] || []);
  // Operating point at the adopted threshold.
  const tp = pos.filter((d) => d < THRESHOLD).length;
  const fp = neg.filter((d) => d < THRESHOLD).length;
  const ox = fp / neg.length, oy = tp / pos.length;
  svg.appendChild(el("circle", { cx: X(ox), cy: Y(oy), r: 6,
                                 fill: "#0D1B2A", stroke: "#00B4D8", "stroke-width": 3 }));
  const lx = X(ox) + 12;
  svg.appendChild(el("text", { x: lx, y: Y(oy) + 1, fill: "#F0F4F8", "font-size": 13 },
                    `threshold ${THRESHOLD}`));
  svg.appendChild(el("text", { x: lx, y: Y(oy) + 17, fill: "#9FB3C8", "font-size": 13 },
                    at.length >= 3
                      ? `TPR ${Number(at[1]).toFixed(2)} · FPR ${Number(at[2]).toFixed(4)}`
                      : "TPR unavailable · FPR unavailable"));

  svg.appendChild(el("text", { x: M.l + iw / 2, y: H - 8, "text-anchor": "middle",
                               fill: "#9FB3C8", "font-size": 13 }, "false positive rate"));
  svg.appendChild(el("text", { x: 15, y: M.t + ih / 2, "text-anchor": "middle",
                               fill: "#9FB3C8", "font-size": 13,
                               transform: `rotate(-90 15 ${M.t + ih / 2})` }, "true positive rate"));
  host.appendChild(svg);

  // Stored figures, rendered as stored — not recomputed for display.
  document.getElementById("auc").textContent =
    loao.auc !== undefined ? Number(loao.auc).toFixed(4) : "—";
  document.getElementById("tpr").textContent =
    at.length >= 3 ? Number(at[1]).toFixed(2) : "unavailable";
  // fpr_at_tpr_1.00 is [threshold, TPR, FPR] — index 2 is the false positive
  // rate. at[1] is the TPR, which is why this stat read 1.0000 while the ROC
  // callout above read 0.1833 off the same file.
  document.getElementById("fpr").textContent =
    at.length >= 3 ? Number(at[2]).toFixed(4) : "unavailable";
}

/* ---------------- histograms ---------------- */
function drawHist(tune) {
  const host = document.getElementById("hist");
  host.textContent = "";
  if (tune.error) { host.appendChild(errBox(tune.error)); return; }

  const series = [
    { key: "variant_sorted",      label: "variant (25)",      color: "#00B4D8" },
    { key: "hard_negative_sorted", label: "hard negative (25)", color: "#FFB703" },
    { key: "cross_target_sorted",  label: "cross target (10)",  color: "#B07BFF" },
  ].filter((s) => Array.isArray(tune[s.key]));

  if (!series.length) {
    host.appendChild(errBox("distance arrays missing from tune_threshold_result.json"));
    return;
  }

  const all = series.flatMap((s) => tune[s.key]);
  const lo = Math.min(...all, THRESHOLD) - 0.02;
  const hi = Math.max(...all, THRESHOLD) + 0.02;
  const BINS = 18;
  const W = 420, rowH = 92, M = { t: 10, r: 16, b: 40, l: 46 };
  const H = M.t + rowH * series.length + M.b;
  const iw = W - M.l - M.r;
  const X = (v) => M.l + ((v - lo) / (hi - lo)) * iw;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H,
                          role: "img", "aria-label": "distance distributions" });

  series.forEach((s, si) => {
    const vals = tune[s.key];
    const top = M.t + si * rowH;
    const bh = rowH - 34;
    const counts = new Array(BINS).fill(0);
    for (const v of vals) {
      let b = Math.floor(((v - lo) / (hi - lo)) * BINS);
      if (b >= BINS) b = BINS - 1;
      if (b < 0) b = 0;
      counts[b]++;
    }
    const maxC = Math.max(...counts, 1);
    const bw = iw / BINS;
    counts.forEach((c, i) => {
      if (!c) return;
      const bhh = (c / maxC) * bh;
      svg.appendChild(el("rect", {
        x: M.l + i * bw + 1, y: top + bh - bhh,
        width: Math.max(bw - 2, 1), height: bhh,
        fill: s.color, opacity: 0.85,
      }));
    });
    svg.appendChild(el("line", { x1: M.l, y1: top + bh, x2: M.l + iw, y2: top + bh,
                                 stroke: "#26415e", "stroke-width": 1 }));
    svg.appendChild(el("text", { x: M.l, y: top - 1, fill: "#F0F4F8", "font-size": 13 }, s.label));
    svg.appendChild(el("line", { x1: X(THRESHOLD), y1: top, x2: X(THRESHOLD), y2: top + bh,
                                 stroke: "#F0F4F8", "stroke-width": 1.5, "stroke-dasharray": "4 4" }));
  });

  for (let i = 0; i <= 5; i++) {
    const v = lo + (i / 5) * (hi - lo);
    svg.appendChild(el("text", { x: X(v), y: H - 18, "text-anchor": "middle",
                                 fill: "#9FB3C8", "font-size": 13 }, v.toFixed(2)));
  }
  svg.appendChild(el("text", { x: M.l + iw / 2, y: H - 2, "text-anchor": "middle",
                               fill: "#9FB3C8", "font-size": 13 },
                    `distance  ·  dashed line = threshold ${THRESHOLD}`));
  host.appendChild(svg);
}

/* ---------------- probe strip ---------------- */
/* Rounding rule is mandatory and deliberate: the identical-text floor is stable
   across runs and shown in full; paraphrase and unrelated drift in trailing
   digits and are shown to three decimals so the page never implies a precision
   the measurement does not have. */
function drawProbe(probe) {
  const host = document.getElementById("probe");
  host.textContent = "";
  if (probe.error) { host.appendChild(errBox(probe.error)); return; }

  const rows = [
    { key: "identical", name: "byte-identical (floor)",
      value: probe.identical, note: "stable across runs — full precision" },
    { key: "paraphrase", name: "paraphrase, same intent",
      value: Number(probe.paraphrase).toFixed(3), note: "rounded — drifts run to run" },
    { key: "unrelated", name: "unrelated topic",
      value: Number(probe.unrelated).toFixed(3), note: "rounded — drifts run to run" },
  ];
  for (const r of rows) {
    const row = h("div", "probe-row");
    const left = h("div");
    left.appendChild(h("div", "probe-name", r.name));
    left.appendChild(h("div", "probe-note", r.note));
    row.appendChild(left);
    row.appendChild(h("div", "probe-val", String(r.value)));
    host.appendChild(row);
  }
}

/* ---------------- folds ---------------- */
function drawFolds(loao) {
  const host = document.getElementById("folds");
  host.textContent = "";
  if (loao.error) { host.appendChild(errBox(loao.error)); return; }
  const folds = loao.fold_results || [];
  if (!folds.length) { host.appendChild(errBox("fold_results missing")); return; }

  const t = h("table");
  const thead = h("thead");
  const hr = h("tr");
  ["held-out archetype", "positives", "negatives", "pool anchors"].forEach((c, i) => {
    const th = h("th", i ? "num" : "", c);
    hr.appendChild(th);
  });
  thead.appendChild(hr); t.appendChild(thead);
  const tb = h("tbody");
  for (const f of folds) {
    const tr = h("tr");
    tr.appendChild(h("td", "", f.k));
    tr.appendChild(h("td", "num", String(f.n_positives)));
    tr.appendChild(h("td", "num", String(f.n_negatives)));
    tr.appendChild(h("td", "num", String(f.n_pool_anchors)));
    tb.appendChild(tr);
  }
  t.appendChild(tb);
  host.appendChild(t);
}

/* ---------------- eval load ---------------- */
fetch("/api/eval").then((r) => r.json()).then((d) => {
  drawRoc(d.loao || {});
  drawHist(d.tune || {});
  drawProbe(d.probe || {});
  drawFolds(d.loao || {});
}).catch((e) => {
  document.getElementById("roc").appendChild(errBox("failed to load /api/eval: " + e));
});

/* ---------------- trace view ---------------- */
let sessionsLoaded = false;

function loadSessions() {
  if (sessionsLoaded) return;
  sessionsLoaded = true;
  const list = document.getElementById("session-list");
  const note = document.getElementById("picker-note");
  list.textContent = "";
  fetch("/api/sessions").then((r) => {
    if (!r.ok) return r.json().then((j) => { throw new Error(j.detail || r.status); });
    return r.json();
  }).then((d) => {
    note.textContent =
      `${d.sessions.length} session${d.sessions.length === 1 ? "" : "s"}, plus ` +
      `${d.null_session_id_trace_groups} trace group${d.null_session_id_trace_groups === 1 ? "" : "s"} ` +
      `covering ${d.null_session_id_spans} spans with no session id.`;
    const all = [...d.sessions, ...d.trace_groups];
    for (const s of all) {
      const b = h("button", "session-btn");
      const title = h("span", "", s.id);
      b.appendChild(title);
      if (s.grouped_by === "trace_id") {
        const badge = h("span", "badge", "trace");
        b.appendChild(badge);
      }
      const dur = s.duration_ms === null ? "—" : `${(s.duration_ms / 1000).toFixed(1)}s`;
      b.appendChild(h("span", "session-meta", `${s.span_count} spans · ${dur}`));
      b.addEventListener("click", () => {
        document.querySelectorAll(".session-btn").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        loadSession(s.id, s.grouped_by);
      });
      list.appendChild(b);
    }
  }).catch((e) => { list.appendChild(errBox(String(e.message || e))); });
}

function kvBlock(parent, label, value) {
  const wrap = h("div", "kv");
  wrap.appendChild(h("div", "kv-key", label));
  const pre = h("pre");
  pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  wrap.appendChild(pre);
  parent.appendChild(wrap);
}

function collapsible(parent, label, value) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const preview = text.length > 300 ? text.slice(0, 300) + " …" : text;
  const det = h("details");
  det.appendChild(h("summary", "", `${label} (${text.length} chars) — expand`));
  const pre = h("pre");
  pre.textContent = text;
  det.appendChild(pre);
  const p = h("pre");
  p.textContent = preview;
  parent.appendChild(h("div", "kv-key", label + " — preview"));
  parent.appendChild(p);
  parent.appendChild(det);
}

function loadSession(id, groupedBy) {
  const host = document.getElementById("timeline");
  const title = document.getElementById("timeline-title");
  host.textContent = "";
  title.textContent = `${id}  ·  grouped by ${groupedBy}`;

  fetch("/api/session/" + encodeURIComponent(id)).then((r) => {
    if (!r.ok) return r.json().then((j) => { throw new Error(j.detail || r.status); });
    return r.json();
  }).then((d) => {
    // Depth by parent chain, so nesting is visible without a layout library.
    const byId = new Map(d.spans.map((s) => [s.span_id, s]));
    const depthOf = (s) => {
      let depth = 0, cur = s, guard = 0;
      while (cur && cur.parent_span_id && byId.has(cur.parent_span_id) && guard++ < 50) {
        cur = byId.get(cur.parent_span_id);
        depth++;
      }
      return depth;
    };

    for (const s of d.spans) {
      const row = h("div", "span-row");
      row.style.marginLeft = `${depthOf(s) * 18}px`;
      const head = h("div", "span-head");
      const isTool = s.name.startsWith("execute_tool");
      head.appendChild(h("span", "span-name" + (isTool ? " tool" : ""), s.name));
      head.appendChild(h("span", "span-dur",
        s.duration_ms === null ? "—" : `${s.duration_ms.toFixed(1)} ms`));
      row.appendChild(head);

      const a = s.attributes || {};
      if (isTool) {
        // Presented exactly as recorded. No judgement is applied here.
        if (a["gcp.vertex.agent.tool_call_args"] !== undefined)
          kvBlock(row, "tool_call_args", a["gcp.vertex.agent.tool_call_args"]);
        if (a["gcp.vertex.agent.tool_response"] !== undefined)
          kvBlock(row, "tool_response", a["gcp.vertex.agent.tool_response"]);
      } else if (s.name === "call_llm") {
        const bits = [];
        if (a["gen_ai.request.model"]) bits.push(`model ${a["gen_ai.request.model"]}`);
        if (a["gen_ai.usage.input_tokens"] !== undefined) bits.push(`in ${a["gen_ai.usage.input_tokens"]}`);
        if (a["gen_ai.usage.output_tokens"] !== undefined) bits.push(`out ${a["gen_ai.usage.output_tokens"]}`);
        if (a["gen_ai.usage.reasoning.output_tokens"] !== undefined)
          bits.push(`reasoning ${a["gen_ai.usage.reasoning.output_tokens"]}`);
        if (bits.length) row.appendChild(h("div", "kv-key", bits.join("  ·  ")));
        if (a["gcp.vertex.agent.llm_request"] !== undefined)
          collapsible(row, "llm_request", a["gcp.vertex.agent.llm_request"]);
        if (a["gcp.vertex.agent.llm_response"] !== undefined)
          collapsible(row, "llm_response", a["gcp.vertex.agent.llm_response"]);
      }
      host.appendChild(row);
    }
  }).catch((e) => { host.appendChild(errBox(String(e.message || e))); });
}
