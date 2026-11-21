/* Soony data explorer: renders explorer/data.json (built by build.py). No dependencies. */
"use strict";

let D = null;
let A = null; // actions from the server (null when served statically)
const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n === null || n === undefined || n === "" ? "–" : typeof n === "number" ? n.toLocaleString("en-US") : esc(n));
const short = (id) => (D.components[id] ? D.components[id].description.replace(/ Grand Heist 6| – Grand Heist 6/g, "").replace(/\s*\(.*\)/, "") : id);
const trunc = (t, n) => (t.length > n ? t.slice(0, n - 1) + "…" : t);
const supName = (id) => (D.suppliers[id] ? D.suppliers[id].name : id || "–");
const docLink = (path, label) => (path ? `<a href="#/docs?path=${encodeURIComponent(path)}">${esc(label || path.split("/").pop())}</a>` : "");
const sevLabel = { critical: "Critical", warning: "Warning", info: "Info" };
const sevIcon = { critical: "!", warning: "!", info: "i" };

// ------------------------------------------------------------------ tooltip
const tip = $("#tip");
function showTip(e, html) {
  tip.innerHTML = html;
  tip.style.display = "block";
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > innerWidth - 8) x = e.clientX - w - pad;
  if (y + h > innerHeight - 8) y = e.clientY - h - pad;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
const hideTip = () => (tip.style.display = "none");
const tipRows = (title, rows) => `<b>${esc(title)}</b>` + rows.map(([k, v]) => `<div class="row"><span>${esc(k)}</span><span>${v}</span></div>`).join("");
function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((n) => {
    n.addEventListener("mousemove", (e) => showTip(e, n.dataset.tip));
    n.addEventListener("mouseleave", hideTip);
  });
}

// ------------------------------------------------------------------ theme
const themeBtn = $("#theme");
const themes = ["auto", "light", "dark"];
function applyTheme(t) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  themeBtn.textContent = "Theme: " + t;
  try { localStorage.setItem("theme", t); } catch (_) {}
}
themeBtn.onclick = () => applyTheme(themes[(themes.indexOf(themeBtn.textContent.split(": ")[1]) + 1) % 3]);
try { applyTheme(localStorage.getItem("theme") || "auto"); } catch (_) { applyTheme("auto"); }

// ------------------------------------------------------------------ table helper
function dataTable(container, rows, cols, opts = {}) {
  const state = { q: "", filters: {}, sort: opts.sort || null, asc: opts.asc ?? false };
  const filterDefs = opts.filters || [];
  const bar = document.createElement("div");
  bar.className = "toolbar";
  bar.innerHTML =
    `<input type="search" placeholder="Search…" aria-label="Search">` +
    filterDefs.map((f, i) => {
      const vals = [...new Set(rows.map((r) => f.get(r)).filter((v) => v !== null && v !== undefined && v !== ""))].sort();
      return `<select data-i="${i}" aria-label="${esc(f.label)}"><option value="">${esc(f.label)}: all</option>${vals.map((v) => `<option>${esc(v)}</option>`).join("")}</select>`;
    }).join("") + `<span class="spacer"></span><span class="muted small count"></span>`;
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  container.append(bar, wrap);
  bar.querySelector("input").oninput = (e) => { state.q = e.target.value.toLowerCase(); draw(); };
  bar.querySelectorAll("select").forEach((s) => (s.onchange = () => { state.filters[s.dataset.i] = s.value; draw(); }));

  function draw() {
    let rs = rows.filter((r) => {
      for (const [i, v] of Object.entries(state.filters)) if (v && String(filterDefs[i].get(r)) !== v) return false;
      if (state.q && !cols.map((c) => c.text ? c.text(r) : r[c.key]).join(" ").toLowerCase().includes(state.q)) return false;
      return true;
    });
    if (state.sort !== null) {
      const c = cols[state.sort], g = c.sortVal || c.text || ((r) => r[c.key]);
      rs = [...rs].sort((a, b) => {
        const x = g(a), y = g(b);
        const r = typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""));
        return state.asc ? r : -r;
      });
    }
    bar.querySelector(".count").textContent = `${rs.length.toLocaleString()} of ${rows.length.toLocaleString()} rows`;
    wrap.innerHTML = `<table><thead><tr>${cols.map((c, i) => `<th data-i="${i}" class="${c.num ? "n" : ""} ${state.sort === i ? "sorted" + (state.asc ? " asc" : "") : ""}">${esc(c.label)}</th>`).join("")}</tr></thead><tbody>` +
      rs.map((r, ri) => `<tr data-ri="${ri}" class="${opts.rowClass ? opts.rowClass(r) : ""} ${opts.onClick ? "clickable" : ""}">${cols.map((c) => `<td class="${c.num ? "n" : ""}">${c.html ? c.html(r) : c.text ? esc(c.text(r)) : c.num ? fmt(r[c.key]) : esc(r[c.key])}</td>`).join("")}</tr>`).join("") +
      `</tbody></table>${rs.length ? "" : '<div class="empty">No rows match.</div>'}`;
    wrap.querySelectorAll("th").forEach((th) => (th.onclick = () => {
      const i = +th.dataset.i;
      if (state.sort === i) state.asc = !state.asc; else { state.sort = i; state.asc = false; }
      draw();
    }));
    if (opts.onClick) wrap.querySelectorAll("tbody tr").forEach((tr) => (tr.onclick = (e) => { if (e.target.tagName !== "A") opts.onClick(rs[+tr.dataset.ri]); }));
  }
  draw();
}

// ------------------------------------------------------------------ pages
const pages = {
  actions: { label: "Actions", render: renderActions, count: () => (A ? A.actions.filter((a) => a.status === "open").length : 0), primary: true },
  overview: { label: "Launch status", render: renderOverview },
  findings: { label: "Findings", render: renderFindings, count: () => D.flags.filter((f) => f.severity !== "info").length },
  parts: { label: "Parts & stock", render: renderParts, count: () => D.coverage.length },
  packout: { label: "Pack-out", render: renderPackout },
  shipments: { label: "Shipments", render: renderShipments, count: () => D.shipments.length },
  pos: { label: "Purchase orders", render: renderPOs, count: () => D.purchase_orders.length },
  grs: { label: "Goods receipts", render: renderGRs, count: () => D.goods_receipts.length },
  suppliers: { label: "Suppliers", render: renderSuppliers, count: () => Object.keys(D.suppliers).length },
  docs: { label: "Documents", render: renderDocs, count: () => D.documents.length },
  context: { label: "Context", render: renderContext },
};

function route() {
  const [name, qs] = (location.hash.slice(2) || "actions").split("?");
  const page = pages[name] ? name : "actions";
  const params = new URLSearchParams(qs || "");
  $("#nav").querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.p === page));
  hideTip();
  const main = $("#main");
  main.innerHTML = "";
  pages[page].render(main, params);
  bindTips(main);
  if (!params.get("path")) window.scrollTo(0, 0);
}

function head(title, sub, right = "") {
  return `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p>${sub}</p>` : ""}</div>${right}</div>`;
}

function countdown() {
  const launch = new Date(D.launch);
  const ref = new Date(D.snapshot_date + "T18:00:00");
  const now = new Date();
  const base = now > ref && now < launch ? now : ref;
  const h = Math.max(0, (launch - base) / 36e5);
  return `<div class="countdown"><b>${Math.floor(h)} h ${Math.round((h % 1) * 60)} min</b><span>to launch · Sun 22 Nov 20:00</span></div>`;
}

// ---------- overview
function renderOverview(main) {
  const eds = Object.entries(D.remaining);
  main.innerHTML = head("Will we make Sunday 20:00?",
    `What the system says versus what the documents say, for the remaining pack-out. Snapshot ${esc(D.snapshot_date)}.`, countdown()) +
    `<div class="grid g2">${eds.map(([pid, e]) => editionCard(pid, e)).join("")}</div>
     <div class="grid g2 section">
       <div class="card"><div class="card-head"><div><h2>Part coverage for the remaining pack-out</h2>
         <p>Share of the parts needed that are available, per part. The line marks 100 %.</p></div></div>
         <div id="cov"></div></div>
       <div class="card"><div class="card-head"><div><h2>What needs attention</h2><p>Top findings. All of them on the Findings page.</p></div>
         <a href="#/actions">Go to actions →</a></div>
         <div class="flags">${D.flags.filter((f) => f.severity !== "info").slice(0, 6).map(flagHtml).join("")}</div></div>
     </div>`;
  coverageChart($("#cov"));
}

function editionCard(pid, e) {
  const b = D.buildable[pid];
  const real = b.adjusted_plus_inbound.units, sys = b.erp_plus_inbound.units, gap = e.to_pack - real;
  const hoursNeeded = e.rate_per_hour ? e.to_pack / e.rate_per_hour : null;
  const status = gap > 0 ? ["critical", `${fmt(gap)} short`] : real < e.to_pack ? ["warning", "At risk"] : ["good", "Covered"];
  const packedPct = e.demand ? (e.packed_erp ?? e.packed) / e.demand : 0;
  const realPct = e.demand ? real / e.demand : 0;
  const limiter = b.adjusted_plus_inbound.limited_by;
  return `<div class="card edition">
    <div class="card-head"><span class="label">${esc(e.edition)} edition</span><span class="pill ${status[0]}">${status[1]}</span></div>
    <div class="hero"><b>${fmt(real)}</b><span>of ${fmt(e.to_pack)} still to pack can be packed</span></div>
    <div class="meter" role="img" aria-label="packed, packable, missing">
      <i style="width:${packedPct * 100}%;background:var(--series-1)" data-tip="${esc(tipRows("Already packed", [["Units", fmt(e.packed_erp ?? e.packed)]]))}"></i>
      <i style="width:${realPct * 100}%;background:var(--series-1-soft)" data-tip="${esc(tipRows("Packable with real parts", [["Units", fmt(real)]]))}"></i>
      ${gap > 0 ? `<i style="width:${(gap / e.demand) * 100}%;background:var(--critical)" data-tip="${esc(tipRows("Missing", [["Units", fmt(gap)]]))}"></i>` : ""}
    </div>
    <div class="legend"><span><i style="background:var(--series-1)"></i>Packed</span><span><i style="background:var(--series-1-soft)"></i>Packable</span>${gap > 0 ? '<span><i style="background:var(--critical)"></i>Missing</span>' : ""}</div>
    <dl class="compare">
      <dt>System view (ERP stock + inbound before launch)</dt><dd>${fmt(sys)}</dd>
      <dt>After document checks</dt><dd><b>${fmt(real)}</b></dd>
      <dt>Limiting part</dt><dd>${limiter ? esc(short(limiter)) : "–"}</dd>
      <dt>Demand · pre-orders</dt><dd>${fmt(e.demand)} · ${fmt(e.preorders)}</dd>
      <dt>Pack hours needed / available</dt><dd>${hoursNeeded ? hoursNeeded.toFixed(1) : "–"} / ${fmt(e.hours_available)}</dd>
    </dl></div>`;
}

function coverageChart(el) {
  const rows = D.coverage.slice().sort((a, b) => cov(a) - cov(b));
  function cov(c) { return c.needed ? (c.adjusted + c.inbound_before_launch) / c.needed : 9; }
  const W = 680, rowH = 30, left = 150, right = 120, top = 18, max = 2;
  const x = (v) => left + (Math.min(v, max) / max) * (W - left - right);
  const H = top + rows.length * rowH + 20;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Part coverage chart">`;
  s += `<g class="grid">${[0, 0.5, 1, 1.5, 2].map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${top - 4}" y2="${H - 18}"/><text x="${x(t)}" y="${H - 4}" text-anchor="middle">${t * 100}%${t === 2 ? "+" : ""}</text>`).join("")}</g>`;
  rows.forEach((c, i) => {
    const y = top + i * rowH, bh = 14, by = y + (rowH - bh) / 2;
    const n = c.needed || 1;
    const segs = [
      ["Usable stock", c.adjusted / n, "var(--series-1)"],
      ["Inbound before launch", c.inbound_before_launch / n, "var(--series-1-soft)"],
      ["Booked but not usable", (c.blocked + c.inflated) / n, "var(--critical)"],
    ];
    let acc = 0;
    const gap = c.adjusted + c.inbound_before_launch - c.needed;
    const tipHtml = esc(tipRows(c.description, [["Needed", fmt(c.needed)], ["ERP stock", fmt(c.erp_stock)], ["Not usable (rejected / over-booked)", fmt(c.blocked + c.inflated)],
      ["Usable stock", fmt(c.adjusted)], ["Inbound before launch", fmt(c.inbound_before_launch)], ["Balance", (gap >= 0 ? "+" : "") + fmt(gap)]]) +
      (c.fitted_by_supplier ? `<div class="small muted" style="margin-top:4px">${esc(c.fitted_by_supplier)}</div>` : ""));
    s += `<g data-tip="${tipHtml}"><rect class="hit" x="0" y="${y}" width="${W}" height="${rowH}"/>`;
    s += `<text class="lbl" x="${left - 8}" y="${y + rowH / 2 + 4}" text-anchor="end">${esc(short(c.component_id))}</text>`;
    segs.forEach(([, v, col]) => {
      if (v <= 0 || acc >= max) return;
      const x0 = x(acc), x1 = x(acc + v);
      if (x1 - x0 > 0.5) s += `<rect class="mark" x="${x0}" y="${by}" width="${Math.max(1, x1 - x0 - 2)}" height="${bh}" rx="3" fill="${col}"/>`;
      acc += v;
    });
    const txt = c.fitted_by_supplier ? "fitted by supplier" : gap < 0 ? `−${fmt(-gap)}` : "ok";
    s += `<text class="${gap < 0 && !c.fitted_by_supplier ? "lbl-strong" : "lbl"}" x="${W - right + 8}" y="${y + rowH / 2 + 4}">${txt}</text></g>`;
  });
  s += `<line class="axis" x1="${x(1)}" x2="${x(1)}" y1="${top - 8}" y2="${H - 18}" stroke-width="2"/><text x="${x(1)}" y="${top - 8}" text-anchor="middle" class="lbl">need</text></svg>`;
  el.innerHTML = s + `<div class="legend"><span><i style="background:var(--series-1)"></i>Usable stock</span><span><i style="background:var(--series-1-soft)"></i>Inbound before launch</span><span><i style="background:var(--critical)"></i>Booked but not usable</span></div>`;
}

function flagHtml(f) {
  return `<div class="flag ${f.severity}"><div class="icon" aria-label="${sevLabel[f.severity]}">${sevIcon[f.severity]}</div>
    <div><div class="t">${esc(f.title)}</div><div class="d">${esc(f.detail)}</div>
    ${f.refs.length ? `<div class="refs">${f.refs.map((r) => docLink(r)).join("")}</div>` : ""}</div>
    <div class="cat">${esc(sevLabel[f.severity])} · ${esc(f.category)}</div></div>`;
}

// ---------- findings
function renderFindings(main) {
  main.innerHTML = head("Findings", "Generated by rules in build.py from the raw files: nothing is typed in by hand. Re-run the build when a new drop lands.") +
    `<div class="flags">${D.flags.map(flagHtml).join("")}</div>
     <div class="section card"><div class="card-head"><div><h2>Delivery notes vs ERP bookings</h2><p>Each scanned delivery note is read by a vision model and compared line by line with what receiving booked. ${D.paper_checks.filter((c) => c.result === "match").length} lines agree.</p></div></div><div id="pc"></div></div>
     <div class="section card"><div class="card-head"><div><h2>Order confirmations vs purchase orders</h2><p>${D.order_confirmations.length} confirmations parsed, ${D.oc_issues.length} differences.</p></div></div><div id="oci"></div></div>
     <div class="section card"><div class="card-head"><div><h2>Shipment tracker vs ERP</h2><p>The Excel tracker compared with the ERP shipment list.</p></div></div><div id="trk"></div></div>`;
  const pcLabel = { match: ["good", "Matches"], mismatch: ["critical", "Mismatch"], to_verify: ["warning", "Verify by eye"], not_booked: ["warning", "Not booked"], not_on_paper: ["warning", "Not on paper"], no_booking: ["warning", "No booking"], unreadable: ["warning", "Unreadable"] };
  const pcRank = { mismatch: 0, not_booked: 1, not_on_paper: 1, no_booking: 1, unreadable: 2, to_verify: 3, match: 4 };
  dataTable($("#pc"), D.paper_checks.slice().sort((a, b) => pcRank[a.result] - pcRank[b.result]), [
    { label: "Result", html: (r) => `<span class="pill ${pcLabel[r.result][0]}">${pcLabel[r.result][1]}</span>`, text: (r) => pcLabel[r.result][1], sortVal: (r) => pcRank[r.result] },
    { label: "Delivery note", html: (r) => docLink(r.path, r.ref), text: (r) => r.ref },
    { label: "Part", text: (r) => (r.material_id ? short(r.material_id) : "–") },
    { label: "Printed", key: "printed", num: true },
    { label: "Paper (final)", key: "paper", num: true },
    { label: "Booked", key: "booked", num: true },
    { label: "GR", key: "gr_number" },
    { label: "Detail", text: (r) => r.detail || (r.hand_corrected ? "Quantity corrected by hand on the paper" : "") },
  ], { filters: [{ label: "Result", get: (r) => pcLabel[r.result][1] }], rowClass: (r) => (r.result === "mismatch" ? "hl" : "") });
  dataTable($("#oci"), D.oc_issues, [
    { label: "Supplier", text: (r) => supName(r.supplier_id) },
    { label: "PO", key: "po_number" },
    { label: "Part", text: (r) => r.material_id ? short(r.material_id) : "–" },
    { label: "Difference", key: "issue" },
    { label: "Note", key: "note" },
    { label: "Document", html: (r) => docLink(r.path), text: (r) => r.path },
  ], { filters: [{ label: "Supplier", get: (r) => supName(r.supplier_id) }, { label: "Type", get: (r) => r.issue.split(" ")[0] }] });
  dataTable($("#trk"), D.tracker_diff, [
    { label: "Shipment", key: "shipment_id" }, { label: "Issue", key: "issue" },
    { label: "ERP status", key: "erp" }, { label: "Tracker status", key: "tracker" }, { label: "Tracker comment", key: "comment" },
  ]);
}

// ---------- parts
function renderParts(main, params) {
  main.innerHTML = head("Parts & stock", "Every part in the bill of materials of the launch editions. Click a row for batches, inbound and suppliers.") + `<div id="t"></div><div id="detail" class="section"></div>`;
  const show = (c) => {
    $("#detail").innerHTML = partDetail(c);
    bindTips($("#detail"));
    $("#detail").scrollIntoView({ behavior: "smooth" });
  };
  dataTable($("#t"), D.coverage, [
    { label: "Part", key: "component_id" },
    { label: "Description", key: "description" },
    { label: "Needed", key: "needed", num: true },
    { label: "ERP stock", key: "erp_stock", num: true },
    { label: "Not usable", num: true, html: (r) => (r.blocked + r.inflated ? `<span class="tag bad">${fmt(r.blocked + r.inflated)}</span>` : "–"), sortVal: (r) => r.blocked + r.inflated },
    { label: "Usable", key: "adjusted", num: true },
    { label: "Inbound before launch", key: "inbound_before_launch", num: true },
    { label: "Balance", num: true, sortVal: (r) => r.adjusted + r.inbound_before_launch - r.needed,
      html: (r) => { const g = r.adjusted + r.inbound_before_launch - r.needed; return r.fitted_by_supplier ? '<span class="tag">fitted by supplier</span>' : g < 0 ? `<b style="color:var(--critical)">−${fmt(-g)}</b>` : "+" + fmt(g); } },
    { label: "Last count", key: "last_count" },
    { label: "Suppliers", text: (r) => r.suppliers.map((s) => s.name).join(", ") },
  ], { sort: 7, asc: true, onClick: show, rowClass: (r) => (r.adjusted + r.inbound_before_launch < r.needed && !r.fitted_by_supplier ? "hl" : "") });
  const pre = params.get("id") && D.coverage.find((c) => c.component_id === params.get("id"));
  if (pre) show(pre);
}

function partDetail(c) {
  const grs = D.goods_receipts.filter((g) => g.material_id === c.component_id).slice(-12).reverse();
  return `<div class="card"><div class="card-head"><div><h2>${esc(c.description)}</h2><p>${esc(c.component_id)} · ${esc(c.category)}</p></div></div>
    ${c.fitted_by_supplier ? `<p class="ink2">${esc(c.fitted_by_supplier)}</p>` : ""}
    <div class="grid g3">
      <div><h3>Stock batches</h3><table><thead><tr><th>Batch</th><th class="n">Qty</th><th></th></tr></thead><tbody>${c.batches.map((b) => {
        const gr = D.goods_receipts.find((g) => g.gr_number === b.batch);
        const insp = D.inspections.find((i) => i.gr_number === b.batch);
        const bad = (insp && insp.rejected) || (gr && gr.qty_ordered && gr.qty_received >= 1.5 * gr.qty_ordered);
        return `<tr class="${bad ? "hl" : ""}"><td>${esc(b.batch || "–")}</td><td class="n">${fmt(b.quantity)}</td><td>${gr && gr.scan ? docLink(gr.scan, "scan") : ""} ${insp ? docLink(insp.path, "inspection") : ""} ${bad ? '<span class="tag bad">check</span>' : ""}</td></tr>`;
      }).join("")}</tbody></table></div>
      <div><h3>Inbound (open shipments)</h3><table><thead><tr><th>Shipment</th><th>At DC</th><th class="n">Qty</th></tr></thead><tbody>${c.inbound.map((i) =>
        `<tr><td>${esc(i.shipment_id)} <span class="muted small">${esc(i.mode)}, ${esc(i.status)}</span></td><td>${esc(i.eta_dc)} ${i.before_launch ? "" : '<span class="tag">after launch</span>'}</td><td class="n">${fmt(i.qty)}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">None</td></tr>'}</tbody></table></div>
      <div><h3>Suppliers</h3><table><thead><tr><th>Supplier</th><th class="n">Share</th><th class="n">Lead time</th></tr></thead><tbody>${c.suppliers.map((s) =>
        `<tr><td><a href="#/suppliers?id=${esc(s.supplier_id)}">${esc(s.name)}</a>${s.primary === "Y" ? ' <span class="tag">primary</span>' : ""}</td><td class="n">${Math.round((s.share || 0) * 100)}%</td><td class="n">${fmt(s.lead_time_days)} d</td></tr>`).join("")}</tbody></table></div>
    </div>
    <div class="section"><h3>Latest goods receipts</h3><table><thead><tr><th>GR</th><th>Date</th><th>PO</th><th>Supplier</th><th class="n">Ordered</th><th class="n">Received</th><th>Remark</th><th>Scan</th></tr></thead><tbody>${grs.map((g) =>
      `<tr class="${g.qty_ordered && g.qty_received >= 1.5 * g.qty_ordered ? "hl" : ""}"><td>${esc(g.gr_number)}</td><td>${esc(g.gr_date)}</td><td>${esc(g.po_number)}</td><td>${esc(supName(g.supplier_id))}</td><td class="n">${fmt(g.qty_ordered)}</td><td class="n">${fmt(g.qty_received)}</td><td>${esc(g.remark)}</td><td>${docLink(g.scan, "scan")}</td></tr>`).join("")}</tbody></table></div></div>`;
}

// ---------- pack-out
function renderPackout(main) {
  const eds = Object.entries(D.remaining);
  main.innerHTML = head("Pack-out", "Units packed per working day at DC Hamburg (pack-out log), and progress towards day-one demand.") +
    `<div class="grid g2">${eds.map(([pid, e]) => `<div class="card"><div class="card-head"><div><h2>${esc(e.edition)}: units per day</h2><p>Planned rate ${fmt(e.rate_per_hour)}/h · ${fmt(e.to_pack)} still to pack</p></div></div><div id="po-${pid}"></div></div>`).join("")}</div>
     <div class="card section"><div class="card-head"><div><h2>Progress towards day-one demand</h2><p>Cumulative packed units as a share of each edition's demand. Dashed: needed by Sunday 20:00.</p></div></div><div id="cum"></div></div>`;
  eds.forEach(([pid, e]) => dailyBars($("#po-" + pid), D.packout.filter((p) => p.product_id === pid), e));
  cumulative($("#cum"), eds);
}

function dailyBars(el, rows, e) {
  const W = 600, H = 220, l = 50, r = 10, t = 10, b = 28;
  const max = Math.max(...rows.map((d) => d.units_packed), 1) * 1.1;
  const bw = (W - l - r) / rows.length;
  const y = (v) => t + (1 - v / max) * (H - t - b);
  const ticks = niceTicks(max, 4);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(e.edition)} daily pack-out">`;
  s += `<g class="grid">${ticks.map((v) => `<line x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}"/><text x="${l - 6}" y="${y(v) + 4}" text-anchor="end">${v >= 1000 ? v / 1000 + "k" : v}</text>`).join("")}</g>`;
  rows.forEach((d, i) => {
    const x = l + i * bw, h = y(0) - y(d.units_packed);
    s += `<g data-tip="${esc(tipRows(d.date, [["Units packed", fmt(d.units_packed)], ["Line", esc(d.line)]]))}"><rect class="hit" x="${x}" y="${t}" width="${bw}" height="${H - t - b}"/>
      <path class="mark" fill="var(--series-1)" d="${barPath(x + 2, y(d.units_packed), bw - 4, h)}"/></g>`;
    if (i % 2 === 0 || rows.length < 10) s += `<text x="${x + bw / 2}" y="${H - 10}" text-anchor="middle">${d.date.slice(5)}</text>`;
  });
  s += `<line class="axis" x1="${l}" x2="${W - r}" y1="${y(0)}" y2="${y(0)}"/></svg>`;
  const hrs = e.rate_per_hour ? e.to_pack / e.rate_per_hour : null;
  el.innerHTML = s + `<p class="small ink2" style="margin:8px 0 0">Best day so far: <b>${fmt(Math.max(...rows.map((d) => d.units_packed)))}</b>. The remaining ${fmt(e.to_pack)} need <b>${hrs ? hrs.toFixed(1) : "–"} h</b> at the planned ${fmt(e.rate_per_hour)}/h; ${fmt(e.hours_available)} h available Sat + Sun.</p>`;
}

function barPath(x, y, w, h) {
  const r = Math.min(4, w / 2, h);
  if (h <= 0) return "";
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function niceTicks(max, n) {
  const step0 = max / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const out = [];
  for (let v = 0; v <= max; v += step) out.push(Math.round(v));
  return out;
}

function cumulative(el, eds) {
  const W = 900, H = 260, l = 44, r = 120, t = 14, b = 28;
  const dates = [...new Set(D.packout.map((p) => p.date))].sort();
  const end = D.launch.slice(0, 10);
  const all = [...dates, end];
  const d0 = new Date(all[0]), d1 = new Date(end);
  const x = (d) => l + ((new Date(d) - d0) / (d1 - d0)) * (W - l - r);
  const y = (v) => t + (1 - v) * (H - t - b);
  const colors = ["var(--series-1)", "var(--series-2)"];
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative pack-out progress">`;
  s += `<g class="grid">${[0, 0.25, 0.5, 0.75, 1].map((v) => `<line x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}"/><text x="${l - 6}" y="${y(v) + 4}" text-anchor="end">${v * 100}%</text>`).join("")}</g>`;
  all.filter((_, i) => i % 3 === 0).forEach((d) => (s += `<text x="${x(d)}" y="${H - 8}" text-anchor="middle">${d.slice(5)}</text>`));
  s += `<line class="axis" x1="${x(end)}" x2="${x(end)}" y1="${t}" y2="${y(0)}"/><text x="${x(end)}" y="${H - 8}" text-anchor="middle" class="lbl">launch</text>`;
  eds.forEach(([pid, e], k) => {
    let acc = 0;
    const pts = D.packout.filter((p) => p.product_id === pid).map((p) => { acc += p.units_packed; return [p.date, acc / e.demand, acc]; });
    const last = pts[pts.length - 1];
    s += `<polyline fill="none" stroke="${colors[k]}" stroke-width="2" points="${pts.map(([d, v]) => `${x(d)},${y(v)}`).join(" ")}"/>`;
    s += `<line stroke="${colors[k]}" stroke-width="2" stroke-dasharray="4 4" x1="${x(last[0])}" y1="${y(last[1])}" x2="${x(end)}" y2="${y(1)}"/>`;
    pts.forEach(([d, v, a]) => (s += `<circle cx="${x(d)}" cy="${y(v)}" r="4" fill="${colors[k]}" stroke="var(--surface)" stroke-width="2" data-tip="${esc(tipRows(e.edition + " · " + d, [["Packed so far", fmt(a)], ["Share of demand", (v * 100).toFixed(1) + "%"]]))}"/>`));
    s += `<text class="lbl-strong" x="${x(end) + 8}" y="${y(1) + 4 + k * 14}">${esc(e.edition)}</text>`;
  });
  s += `</svg>`;
  el.innerHTML = s + `<div class="legend">${eds.map(([, e], k) => `<span><i style="background:${colors[k]}"></i>${esc(e.edition)}</span>`).join("")}</div>`;
}

// ---------- shipments
const shipState = (s) => (["arrived_port", "in_delivery", "delivered"].includes(s.status) ? ["good", "Arrived / delivering"] :
  s.status === "delayed" ? ["critical", "Delayed"] : s.status === "booked" ? ["info", "Booked, not moving"] : ["series", "In transit"]);
const stateFill = { good: "var(--good)", critical: "var(--critical)", info: "var(--axis)", series: "var(--series-1)" };

function renderShipments(main) {
  main.innerHTML = head("Shipments", "Open shipments from the ERP list. Bars run from departure to the estimated arrival at DC Hamburg (including the last road leg).") +
    `<div class="card"><div id="gantt"></div></div><div class="section" id="t"></div>`;
  gantt($("#gantt"));
  dataTable($("#t"), D.shipments, [
    { label: "Shipment", key: "shipment_id" },
    { label: "Supplier", text: (r) => supName(r.supplier_id) },
    { label: "Mode", key: "mode" },
    { label: "Parts", text: (r) => r.material_ids.split("|").map(short).join(", ") },
    { label: "Qty", num: true, sortVal: (r) => r.lines.reduce((a, l) => a + l.quantity, 0), html: (r) => fmt(r.lines.reduce((a, l) => a + l.quantity, 0)) },
    { label: "Route", text: (r) => `${r.origin} → ${r.destination}` },
    { label: "ETD", key: "etd" }, { label: "ETA", key: "eta" }, { label: "At DC", key: "eta_dc" },
    { label: "Before launch", text: (r) => (r.before_launch ? "yes" : "no"), html: (r) => (r.before_launch ? '<span class="pill good">Yes</span>' : '<span class="pill info">No</span>') },
    { label: "Status", html: (r) => { const [c, l] = shipState(r); return `<span class="pill ${c === "series" ? "info" : c}">${esc(r.status)}</span>`; }, text: (r) => r.status },
    { label: "Updated", key: "updated_at" }, { label: "Note", key: "note" },
  ], { filters: [{ label: "Status", get: (r) => r.status }, { label: "Supplier", get: (r) => supName(r.supplier_id) }, { label: "Before launch", get: (r) => (r.before_launch ? "yes" : "no") }], sort: 8, asc: true });
}

function gantt(el) {
  const rows = D.shipments.slice().sort((a, b) => a.eta_dc.localeCompare(b.eta_dc));
  const W = 1000, l = 230, r = 20, t = 24, rowH = 22, b = 26, H = t + rows.length * rowH + b;
  const d0 = new Date(rows.reduce((m, s) => (s.etd < m ? s.etd : m), rows[0].etd));
  const d1 = new Date(rows.reduce((m, s) => (s.eta_dc > m ? s.eta_dc : m), rows[0].eta_dc));
  const x = (d) => l + ((new Date(d) - d0) / (d1 - d0)) * (W - l - r);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Shipment timeline">`;
  const months = [];
  for (let d = new Date(d0.getFullYear(), d0.getMonth(), 1); d <= d1; d.setDate(d.getDate() + 7)) months.push(new Date(d));
  s += `<g class="grid">${months.filter((d) => d >= d0).map((d) => { const iso = d.toISOString().slice(0, 10); return `<line x1="${x(iso)}" x2="${x(iso)}" y1="${t - 6}" y2="${H - b}"/><text x="${x(iso)}" y="${H - 8}" text-anchor="middle">${iso.slice(5)}</text>`; }).join("")}</g>`;
  rows.forEach((sh, i) => {
    const y = t + i * rowH, [st, lab] = shipState(sh);
    const qty = sh.lines.reduce((a, ln) => a + ln.quantity, 0);
    const tp = esc(tipRows(sh.shipment_id, [["Supplier", esc(supName(sh.supplier_id))], ["Parts", esc(sh.material_ids.split("|").map(short).join(", "))], ["Quantity", fmt(qty)],
      ["Mode", esc(sh.mode)], ["Route", esc(`${sh.origin} → ${sh.destination}`)], ["Departs", esc(sh.etd)], ["At DC", esc(sh.eta_dc)], ["Status", esc(sh.status)]]) + (sh.note ? `<div class="small muted">${esc(sh.note)}</div>` : ""));
    s += `<g data-tip="${tp}"><rect class="hit" x="0" y="${y}" width="${W}" height="${rowH}"/>`;
    s += `<text class="lbl" x="8" y="${y + 15}">${esc(sh.shipment_id.slice(-5))} · ${esc(trunc(sh.material_ids.split("|").map(short).join(", "), 30))}</text>`;
    const x0 = x(sh.etd), x1 = Math.max(x(sh.eta_dc), x0 + 6);
    s += st === "info"
      ? `<rect class="mark" x="${x0}" y="${y + 5}" width="${x1 - x0}" height="12" rx="4" fill="none" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="3 2"/>`
      : `<rect class="mark" x="${x0}" y="${y + 5}" width="${x1 - x0}" height="12" rx="4" fill="${stateFill[st]}"/>`;
    s += `</g>`;
  });
  const lx = x(D.launch.slice(0, 10));
  s += `<line x1="${lx}" x2="${lx}" y1="${t - 14}" y2="${H - b}" stroke="var(--critical)" stroke-width="2"/><text x="${lx + 4}" y="${t - 10}" class="lbl-strong">Launch Sun 22 Nov</text></svg>`;
  el.innerHTML = s + `<div class="legend"><span><i style="background:var(--good)"></i>Arrived / delivering</span><span><i style="background:var(--series-1)"></i>In transit</span><span><i style="background:var(--critical)"></i>Delayed</span><span><i style="border:1.5px dashed var(--muted)"></i>Booked, not moving</span><span class="muted">Left of the red line = arrives before launch</span></div>`;
}

// ---------- POs & GRs
function renderPOs(main) {
  main.innerHTML = head("Purchase orders", "Both SAP exports merged (legacy 2024–H1 2025 export normalised: supplier numbers, US dates, decimal commas).") + `<div id="t"></div>`;
  dataTable($("#t"), D.purchase_orders, [
    { label: "PO", key: "po_number" }, { label: "Line", key: "po_line", num: true },
    { label: "Supplier", text: (r) => supName(r.supplier_id) },
    { label: "Part", text: (r) => `${r.material_id} · ${short(r.material_id)}` },
    { label: "Qty", key: "quantity", num: true },
    { label: "Price", num: true, html: (r) => `${fmt(r.unit_price)} ${esc(r.currency || "")}`, sortVal: (r) => r.unit_price },
    { label: "Ordered", key: "order_date" }, { label: "Requested", key: "requested_date" }, { label: "Promised", key: "promised_date" }, { label: "Delivered", key: "actual_delivery_date" },
    { label: "Status", html: (r) => `<span class="tag ${r.status === "awaiting_approval" ? "bad" : ""}">${esc(r.status)}</span>`, text: (r) => r.status },
    { label: "Buyer", key: "buyer" }, { label: "Source", key: "source" },
  ], { filters: [{ label: "Supplier", get: (r) => supName(r.supplier_id) }, { label: "Part", get: (r) => r.material_id }, { label: "Status", get: (r) => r.status }, { label: "Buyer", get: (r) => r.buyer }], sort: 6 });
}

function renderGRs(main) {
  main.innerHTML = head("Goods receipts", "Every booking at DC Hamburg. Highlighted rows: booked far above the ordered quantity, no PO, or a rejected inspection.") + `<div id="t"></div>`;
  const rejected = new Set(D.inspections.filter((i) => i.rejected).map((i) => i.gr_number));
  dataTable($("#t"), D.goods_receipts, [
    { label: "GR", key: "gr_number" }, { label: "Date", key: "gr_date" }, { label: "PO", key: "po_number" },
    { label: "Supplier", text: (r) => supName(r.supplier_id) },
    { label: "Part", text: (r) => r.material_id + (D.components[r.material_id] ? " · " + short(r.material_id) : "") },
    { label: "Ordered", key: "qty_ordered", num: true }, { label: "Received", key: "qty_received", num: true },
    { label: "Remark", html: (r) => (r.remark ? `<span class="tag">${esc(r.remark)}</span>` : "") + (rejected.has(r.gr_number) ? ' <span class="tag bad">inspection rejected</span>' : ""), text: (r) => r.remark },
    { label: "Paper check", text: (r) => r.paper || (r.scan ? "not read" : "no scan"),
      html: (r) => (r.paper === "match" ? '<span class="pill good">Matches paper</span>' : r.paper === "mismatch" ? '<span class="pill critical">Differs from paper</span>' : `<span class="muted small">${r.scan ? "scan not read" : "no scan"}</span>`) },
    { label: "Inspector", key: "inspector" },
    { label: "Delivery note", html: (r) => (r.scan ? docLink(r.scan, r.delivery_note) : esc(r.delivery_note)), text: (r) => r.delivery_note },
  ], {
    filters: [{ label: "Supplier", get: (r) => supName(r.supplier_id) }, { label: "Part", get: (r) => r.material_id }, { label: "Remark", get: (r) => r.remark || "(none)" }, { label: "Paper check", get: (r) => r.paper || (r.scan ? "not read" : "no scan") }],
    sort: 1, rowClass: (r) => (rejected.has(r.gr_number) || !r.po_number || r.paper === "mismatch" || (r.qty_ordered && r.qty_received >= 1.5 * r.qty_ordered) ? "hl" : ""),
  });
}

// ---------- suppliers
function renderSuppliers(main, params) {
  const sel = params.get("id");
  const list = Object.values(D.suppliers);
  main.innerHTML = head("Suppliers", "Profiles, parts, open orders and documents per supplier.") + `<div class="grid g2">${list.map((s) => supplierCard(s, s.supplier_id === sel)).join("")}</div>`;
  if (sel) document.getElementById("sup-" + sel)?.scrollIntoView();
}

function supplierCard(s, open) {
  const pos = D.purchase_orders.filter((p) => p.supplier_id === s.supplier_id);
  const openPos = pos.filter((p) => p.status !== "delivered" && p.status !== "cancelled");
  const docs = D.documents.filter((d) => d.supplier_id === s.supplier_id);
  const flags = D.flags.filter((f) => f.title.includes(s.name) || f.detail.includes(s.supplier_id) || f.detail.includes(s.name));
  const kinds = {};
  docs.forEach((d) => (kinds[d.kind] = (kinds[d.kind] || 0) + 1));
  const ship = D.shipments.filter((x) => x.supplier_id === s.supplier_id);
  return `<div class="card supplier-card" id="sup-${esc(s.supplier_id)}" ${open ? 'style="outline:2px solid var(--series-1)"' : ""}>
    <div class="card-head"><div><h2>${esc(s.name)}</h2><p>${esc(s.legal_name)} · ${esc(s.city)}, ${esc(s.country)}</p></div>
    <span class="pill ${s.qualification_status === "qualified" ? "good" : "warning"}">${esc(s.qualification_status)}</span></div>
    <dl class="kv">
      <dt>ID</dt><dd>${esc(s.supplier_id)}</dd><dt>Category</dt><dd>${esc(s.category)}</dd>
      <dt>Contact</dt><dd>${esc(s.contact_name)} · ${esc(s.contact_email)} · ${esc(s.phone)}</dd>
      <dt>Language</dt><dd>${esc(s.preferred_language)}</dd>
      <dt>Terms</dt><dd>${esc(s.incoterm)} · ${esc(s.payment_terms)} · ${esc(s.currency)}</dd>
      <dt>Since</dt><dd>${esc(s.supplier_since)}${s.conditional_expires ? ` · conditional release ended ${esc(s.conditional_expires)}` : ""}</dd>
      ${s.notes ? `<dt>Notes</dt><dd>${esc(s.notes)}</dd>` : ""}
      <dt>Orders</dt><dd>${pos.length} PO lines, ${openPos.length} open · ${ship.length} open shipments</dd>
      <dt>Documents</dt><dd>${Object.entries(kinds).map(([k, n]) => `<a href="#/docs?supplier=${esc(s.supplier_id)}&kind=${esc(k)}">${n} ${esc(k.replace(/_/g, " "))}</a>`).join(" · ") || "–"}</dd>
    </dl>
    <table class="components section"><thead><tr><th>Part</th><th class="n">Share</th><th class="n">Price</th><th class="n">Lead time</th><th class="n">MOQ</th></tr></thead><tbody>
      ${s.components.map((c) => `<tr><td><a href="#/parts?id=${esc(c.component_id)}">${esc(short(c.component_id))}</a>${c.note ? `<div class="small muted">${esc(c.note)}</div>` : ""}</td><td class="n">${Math.round((c.share || 0) * 100)}%</td><td class="n">${fmt(c.unit_price)} ${esc(c.currency)}</td><td class="n">${fmt(c.lead_time_days)} d</td><td class="n">${fmt(c.moq)}</td></tr>`).join("")}
    </tbody></table>
    ${flags.length ? `<details class="expand" ${open ? "open" : ""}><summary>${flags.length} finding(s)</summary><div class="flags" style="margin-top:8px">${flags.map(flagHtml).join("")}</div></details>` : ""}
  </div>`;
}

// ---------- documents
function renderDocs(main, params) {
  main.innerHTML = head("Documents", "Every file in the snapshot: delivery-note scans, order confirmations, contracts, notices, reports and spreadsheets. Search includes the PDF text.") +
    `<div class="toolbar"><input type="search" id="dq" placeholder="Search names and text…" aria-label="Search documents">
      <select id="dk" aria-label="Kind"><option value="">Kind: all</option></select>
      <select id="ds" aria-label="Supplier"><option value="">Supplier: all</option></select><span class="spacer"></span><span class="muted small" id="dc"></span></div>
     <div class="docs"><div class="doc-list" id="dl"></div><div class="card viewer" id="dv"><div class="empty">Select a document.</div></div></div>`;
  const kinds = [...new Set(D.documents.map((d) => d.kind))].sort();
  $("#dk").innerHTML += kinds.map((k) => `<option value="${esc(k)}">${esc(k.replace(/_/g, " "))}</option>`).join("");
  $("#ds").innerHTML += Object.values(D.suppliers).map((s) => `<option value="${esc(s.supplier_id)}">${esc(s.name)}</option>`).join("");
  if (params.get("kind")) $("#dk").value = params.get("kind");
  if (params.get("supplier")) $("#ds").value = params.get("supplier");
  let current = params.get("path");
  const draw = () => {
    const q = $("#dq").value.toLowerCase(), k = $("#dk").value, s = $("#ds").value;
    const rows = D.documents.filter((d) => (!k || d.kind === k) && (!s || d.supplier_id === s) && (!q || (d.path + " " + (d.text || "")).toLowerCase().includes(q)));
    $("#dc").textContent = `${rows.length} of ${D.documents.length}`;
    $("#dl").innerHTML = rows.map((d) => `<div class="doc-item ${d.path === current ? "active" : ""}" data-p="${esc(d.path)}"><span class="n">${esc(d.name)}</span>
      <span class="small muted">${esc(d.kind.replace(/_/g, " "))}${d.supplier_id ? " · " + esc(supName(d.supplier_id)) : ""}${d.date ? " · " + esc(d.date) : ""}${d.read ? " · read by model" : d.scanned ? " · scanned, not read" : ""}</span></div>`).join("") || '<div class="empty">No documents match.</div>';
    $("#dl").querySelectorAll(".doc-item").forEach((n) => (n.onclick = () => { current = n.dataset.p; view(current); draw(); }));
  };
  ["#dq", "#dk", "#ds"].forEach((s) => ($(s).oninput = draw));
  draw();
  if (current) view(current);
}

function view(path) {
  const d = D.documents.find((x) => x.path === path);
  const v = $("#dv");
  if (!d) { v.innerHTML = `<div class="empty">Not found: ${esc(path)}</div>`; return; }
  const url = "../" + d.path.split("/").map(encodeURIComponent).join("/");
  const gr = D.goods_receipts.filter((g) => g.scan === d.path);
  let body = "";
  if (["jpg", "jpeg", "png"].includes(d.ext)) body = `<img src="${url}" alt="${esc(d.name)}">`;
  else if (d.ext === "pdf") body = (d.text ? `<details class="expand" open><summary>Extracted text</summary><pre class="text">${esc(d.text)}</pre></details>` : `<p class="muted small">Scanned PDF without a text layer: run explorer/read_scans.py to read it.</p>`) + `<iframe src="${url}" title="${esc(d.name)}" style="margin-top:12px"></iframe>`;
  else if (d.sheets) body = Object.entries(d.sheets).map(([n, rows]) => `<h3 style="margin:12px 0 6px">${esc(n)}</h3><div class="table-wrap"><table><tbody>${rows.map((r, i) => `<tr>${r.map((c) => (i === 0 ? `<th>${esc(c)}</th>` : `<td class="${typeof c === "number" ? "n" : ""}">${fmt(c)}</td>`)).join("")}</tr>`).join("")}</tbody></table></div>`).join("");
  else body = `<a href="${url}">Open file</a>`;
  const read = d.read ? readPanel(d, gr) : "";
  v.innerHTML = `<div class="card-head"><div><h2 style="overflow-wrap:anywhere">${esc(d.name)}</h2><p>${esc(d.path)} · ${(d.size / 1024).toFixed(0)} KB</p></div><a href="${url}" target="_blank" rel="noopener">Open ↗</a></div>
    ${gr.length ? `<div class="flags" style="margin-bottom:12px">${gr.map((g) => `<div class="flag ${g.paper === "mismatch" || (g.qty_ordered && g.qty_received >= 1.5 * g.qty_ordered) ? "critical" : "info"}"><div class="icon">${g.paper === "mismatch" || (g.qty_ordered && g.qty_received >= 1.5 * g.qty_ordered) ? "!" : "i"}</div><div><div class="t">Booked in ERP as GR ${esc(g.gr_number)}</div><div class="d">${esc(g.material_id)} · ordered ${fmt(g.qty_ordered)} · booked ${fmt(g.qty_received)} · ${esc(g.gr_date)} ${g.remark ? "· " + esc(g.remark) : ""}</div></div><div class="cat">Goods receipt</div></div>`).join("")}</div>` : ""}
    ${read}${body}`;
}

function readPanel(d, grs) {
  const r = d.read, list = (a) => (a && a.length ? `<ul style="margin:4px 0 0;padding-left:18px">${a.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "");
  const by = `<p class="small muted" style="margin:8px 0 0">Read by ${esc(r.model)} on ${esc((r.read_at || "").replace("T", " "))}. Machine reading: check the image for anything that matters.</p>`;
  if (r.lines) {
    return `<div class="card" style="margin-bottom:12px;box-shadow:none"><h3>What the paper says</h3>
      <table style="margin-top:6px"><thead><tr><th>Part</th><th class="n">Printed</th><th class="n">Final on paper</th><th class="n">Booked in ERP</th><th></th></tr></thead><tbody>${r.lines.map((l) => {
        const g = grs.find((x) => x.material_id === l.soony_material_id && x.qty_received === l.final_quantity) || grs.find((x) => x.material_id === l.soony_material_id);
        const bad = g && l.final_quantity !== null && g.qty_received !== l.final_quantity;
        return `<tr class="${bad ? "hl" : ""}"><td>${esc(l.material_id)}${l.soony_material_id && l.soony_material_id !== l.material_id ? ` <span class="muted small">= ${esc(l.soony_material_id)}</span>` : ""}<div class="small muted">${esc(l.description || "")}</div></td>
          <td class="n">${esc(l.printed_quantity_text)}</td><td class="n"><b>${esc(l.final_quantity_text)}</b></td><td class="n">${g ? fmt(g.qty_received) : "–"}</td>
          <td>${l.handwritten_correction ? `<span class="tag ${l.corrected_field === "quantity" ? "bad" : ""}">hand-corrected: ${esc(l.corrected_field || "?")}</span>` : ""} ${bad ? '<span class="tag bad">differs</span>' : g ? '<span class="tag">matches</span>' : ""}</td></tr>`;
      }).join("")}</tbody></table>
      <dl class="kv" style="margin-top:10px">
        ${r.po_number ? `<dt>PO on paper</dt><dd>${esc(r.po_number)}</dd>` : ""}
        ${r.received_by ? `<dt>Received by</dt><dd>${esc(r.received_by)}${r.received_stamp_date ? " · stamped " + esc(r.received_stamp_date) : ""}</dd>` : ""}
        ${r.remarks && !/^(null|n\/a)$/i.test(r.remarks) ? `<dt>Remarks</dt><dd>${esc(r.remarks)}</dd>` : ""}
        ${r.handwritten_notes && r.handwritten_notes.length ? `<dt>Pen notes</dt><dd>${list(r.handwritten_notes)}</dd>` : ""}
        ${r.anomalies && r.anomalies.length ? `<dt>Noticed</dt><dd>${list(r.anomalies)}</dd>` : ""}
      </dl>${by}</div>`;
  }
  return `<div class="card" style="margin-bottom:12px;box-shadow:none"><h3>${esc(r.title || r.document_type || "Document")}</h3>
    <p class="ink2" style="margin:6px 0">${esc(r.summary || "")}</p>
    <dl class="kv">${(r.parties || []).length ? `<dt>Parties</dt><dd>${esc(r.parties.join(" · "))}</dd>` : ""}${r.effective_date ? `<dt>Effective</dt><dd>${esc(r.effective_date)}</dd>` : ""}${r.term_and_termination ? `<dt>Term</dt><dd>${esc(r.term_and_termination)}</dd>` : ""}</dl>
    <table style="margin-top:10px"><thead><tr><th>Topic</th><th>Clause</th><th>What it says</th></tr></thead><tbody>${(r.key_terms || []).map((t) => `<tr><td style="white-space:normal"><b>${esc(t.topic)}</b></td><td>${esc(t.clause || "")}</td><td>${esc(t.what_it_says)}</td></tr>`).join("")}</tbody></table>
    ${r.anomalies && r.anomalies.length ? `<p class="small"><b>Noticed:</b></p>${list(r.anomalies)}` : ""}${by}</div>`;
}

// ---------- context
function renderContext(main) {
  const lp = D.launch_plan;
  main.innerHTML = head("Context", "Onboarding notes and Soony's own launch plan, as they gave it to us.") +
    `<div class="grid g2"><div class="card md">${Object.entries(D.context_md).map(([p, t]) => `<p class="small muted">${esc(p)}</p>${md(t)}`).join("")}</div>
     <div class="card"><div class="card-head"><div><h2>Launch plan (Soony's spreadsheet)</h2><p>${esc(lp.title || "")} · ${docLink(lp.file)}</p></div></div>
     ${Object.entries(lp.sheets || {}).map(([n, rows]) => rows.length ? `<h3 style="margin:12px 0 6px">${esc(n)}</h3><div class="table-wrap" style="max-height:none"><table><thead><tr>${Object.keys(rows[0]).map((k) => `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${Object.values(r).map((c) => `<td class="${typeof c === "number" ? "n" : ""}">${fmt(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "").join("")}
     </div></div>`;
}

function md(t) {
  return t.split(/\n{2,}/).map((block) => {
    if (block.startsWith("# ")) return `<h1>${esc(block.slice(2))}</h1>`;
    if (block.startsWith("## ")) return `<h2>${esc(block.slice(3))}</h2>`;
    if (block.split("\n").every((l) => l.startsWith("- "))) return `<ul>${block.split("\n").map((l) => `<li>${esc(l.slice(2))}</li>`).join("")}</ul>`;
    return `<p>${esc(block)}</p>`;
  }).join("").replace(/`([^`]+)`/g, "<code>$1</code>");
}

// ------------------------------------------------------------------ actions (main screen)
const api = (path, body) => fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" })
  .then(async (r) => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; });
const ui = { tab: "open", sel: null, editing: false, notice: null };
const tabs = { open: ["To send", (a) => a.status === "open"], sent: ["Waiting for reply", (a) => a.status === "sent"], closed: ["Closed", (a) => a.status === "done" || a.status === "dismissed"] };
const langName = { pl: "Polish", zh: "Chinese", ko: "Korean", en: "English", de: "German" };
const modeText = () => ({ agentmail: `Sends from ${A.sender} through AgentMail`, gmail: `Sends from ${A.sender} through Gmail`, compose: "Opens a pre-filled Gmail compose window", "dry-run": "Dry run: nothing leaves this machine" }[A.mode]);

function renderNav() {
  $("#nav").innerHTML = Object.entries(pages).map(([k, p], i) =>
    `${i === 1 ? '<div class="nav-group">Ground truth</div>' : ""}<a href="#/${k}" data-p="${k}" class="${p.primary ? "primary" : ""}"><span>${p.label}</span>${p.count ? `<span class="count">${p.count()}</span>` : ""}</a>`).join("");
  const cur = (location.hash.slice(2) || "actions").split("?")[0];
  $("#nav").querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.p === (pages[cur] ? cur : "actions")));
}

function renderActions(main, params) {
  if (!A) {
    main.innerHTML = head("Actions", "") + `<div class="empty">The action inbox needs the app server. Run <code>python3 explorer/server.py</code> from the asklio folder and reload.</div>`;
    return;
  }
  if (params && params.get("id")) { ui.sel = params.get("id"); const a = A.actions.find((x) => x.id === ui.sel); if (a) ui.tab = Object.keys(tabs).find((t) => tabs[t][1](a)); }
  const list = A.actions.filter(tabs[ui.tab][1]);
  if (!list.find((a) => a.id === ui.sel)) { ui.sel = list[0] ? list[0].id : null; ui.editing = false; }
  const sel = A.actions.find((a) => a.id === ui.sel);
  const open = A.actions.filter(tabs.open[1]);
  main.innerHTML = head("Reconcile and act",
    `Where the system and the evidence disagree, an email is drafted to the person who can confirm or fix it. You review, edit if needed, and send. ${esc(modeText())}.`, countdown()) +
    (A.problem ? `<div class="banner bad" style="margin-bottom:16px">${esc(A.problem)} Until then, Send opens Gmail compose in your browser.</div>` : "") +
    `<div class="act">
      <div class="act-list">
        <div class="seg" role="tablist">${Object.entries(tabs).map(([k, [label, f]]) => `<button role="tab" aria-selected="${ui.tab === k}" data-tab="${k}">${label} <span>${A.actions.filter(f).length}</span></button>`).join("")}</div>
        ${list.map((a) => `<button class="act-item ${a.id === ui.sel ? "active" : ""}" data-id="${a.id}">
            <span class="row1"><span class="pill ${a.severity}">${sevLabel[a.severity]}</span><span class="muted small">${a.reply_by ? "reply by " + esc(a.reply_by.replace(/ CET$/, "")) : ""}</span></span>
            <span class="t">${esc(a.title)}</span>
            <span class="small ink2">To ${esc(a.recipient_name)}${a.recipient_role ? " · " + esc(a.recipient_role) : ""}</span>
            ${a.to ? "" : '<span class="tag bad">address missing</span>'}${a.edited ? ' <span class="tag">edited</span>' : ""}
          </button>`).join("") || `<div class="empty">${ui.tab === "open" ? "Nothing left to send." : "Nothing here yet."}</div>`}
        ${ui.tab === "open" && A.no_action.length ? `<details class="expand quiet"><summary>${A.no_action.length} case(s) checked, no email needed</summary>${A.no_action.map((q) => `<div class="q"><b>${esc(q.case_name)}</b><div class="small ink2">${esc(q.no_email_reason || q.assessment)}</div></div>`).join("")}</details>` : ""}
      </div>
      <div class="act-detail" id="detail">${sel ? actionDetail(sel) : `<div class="card empty">${open.length ? "Select an action." : "All actions handled."}</div>`}</div>
    </div>`;
  main.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { ui.tab = b.dataset.tab; ui.sel = null; ui.editing = false; ui.notice = null; rerender(); }));
  main.querySelectorAll(".act-item").forEach((b) => (b.onclick = () => { ui.sel = b.dataset.id; ui.editing = false; ui.notice = null; rerender(); }));
  if (sel) bindAction(sel);
}

function rerender() { renderNav(); const m = $("#main"); const y = scrollY; m.innerHTML = ""; renderActions(m); bindTips(m); scrollTo(0, y); }

function truthBlock(a) {
  const t = a.truth;
  const imgs = a.evidence.filter((p) => /\.(jpe?g|png)$/i.test(p));
  const others = a.evidence.filter((p) => !/\.(jpe?g|png)$/i.test(p));
  let nums = "";
  if (t && !t.fitted_by_supplier) {
    const gap = t.balance;
    nums = `<div class="truth-nums">
      <div><span>System says</span><b>${fmt(t.system)}</b><i>ERP stock</i></div>
      <div class="${t.not_usable ? "bad" : ""}"><span>Evidence says</span><b>${fmt(t.evidence)}</b><i>${t.not_usable ? fmt(t.not_usable) + " not real or not usable" : "matches the system"}</i></div>
      <div><span>Needed</span><b>${fmt(t.needed)}</b><i>${t.inbound_before_launch ? "+" + fmt(t.inbound_before_launch) + " inbound before launch" : "for the remaining pack-out"}</i></div>
      <div class="${gap < 0 ? "bad" : "ok"}"><span>${gap < 0 ? "Short" : "Spare"}</span><b>${fmt(Math.abs(gap))}</b><i>${gap < 0 ? "copies at risk" : "after the remaining pack-out"}</i></div>
    </div>`;
  }
  return `<div class="card truth">
    <div class="card-head"><div><h2>Ground truth</h2><p>${esc(a.case_name)}${a.material_id ? ` · <a href="#/parts?id=${esc(a.material_id)}">${esc(a.material_id)}</a>` : ""}</p></div></div>
    ${nums}
    <p class="ink2" style="margin:10px 0 8px">${esc(a.assessment)}</p>
    <ul class="facts">${a.findings.map((f) => `<li><span class="pill ${f.severity}">${esc(f.category)}</span> <b>${esc(f.title)}</b><div class="small ink2">${esc(f.detail)}</div></li>`).join("")}</ul>
    ${imgs.length ? `<div class="thumbs">${imgs.map((p) => `<a href="#/docs?path=${encodeURIComponent(p)}" title="${esc(p.split("/").pop())}"><img loading="lazy" src="../${p.split("/").map(encodeURIComponent).join("/")}" alt="${esc(p.split("/").pop())}"><span>${esc(p.split("/").pop())}</span></a>`).join("")}</div>` : ""}
    ${others.length ? `<div class="refs small">Sources: ${others.map((p) => docLink(p)).join(" · ")}</div>` : ""}
  </div>`;
}

function actionDetail(a) {
  const e = ui.editing, closed = a.status === "done" || a.status === "dismissed";
  const field = (label, key, extra = "") => e
    ? `<label>${label}<input id="f-${key}" value="${esc(a[key])}" ${extra}></label>`
    : `<div class="ro"><span>${label}</span><div>${a[key] ? esc(a[key]) : key === "to" ? '<span class="tag bad">add an address</span>' : '<span class="muted">–</span>'}</div></div>`;
  const last = a.history[a.history.length - 1];
  const status = a.status === "sent" ? `<div class="banner good">Sent${last ? " · " + esc(last.at.replace("T", " ").slice(0, 16)) : ""}. Waiting for: ${esc(a.ask)}</div>`
    : a.status === "done" ? `<div class="banner good">Resolved.</div>` : a.status === "dismissed" ? `<div class="banner">Dismissed.</div>`
    : last && last.event.startsWith("opened in Gmail") ? `<div class="banner">Opened in Gmail compose. If you sent it there, mark it as sent.</div>` : "";
  return `${truthBlock(a)}
  <div class="card mail">
    <div class="card-head"><div><h2>${esc(a.title)}</h2><p>${esc(a.why_this_recipient || "")}</p></div>
      <span class="pill ${a.severity}">${sevLabel[a.severity]}</span></div>
    ${status}${ui.notice ? `<div class="banner ${ui.notice[0]}">${esc(ui.notice[1])}</div>` : ""}
    <div class="mail-form ${e ? "editing" : ""}">
      ${field("To", "to", 'type="text" placeholder="name@company.com" autocomplete="off"')}
      ${field("Cc", "cc", 'type="text" autocomplete="off"')}
      ${field("Subject", "subject", 'type="text"')}
      ${e ? `<label>Message<textarea id="f-body" rows="${Math.min(24, Math.max(10, a.body.split("\n").length + 2))}">${esc(a.body)}</textarea></label>` : `<pre class="body">${esc(a.body)}</pre>`}
    </div>
    ${a.language !== "en" && a.body_english ? `<details class="expand"><summary>English version of the ${esc(langName[a.language] || a.language)} draft${a.edited ? " (your edits are not reflected here)" : ""}</summary><pre class="body tr">${esc(a.body_english)}</pre></details>` : ""}
    <div class="mail-actions">
      ${closed ? `<button class="btn" data-do="reopen">Reopen</button>` : a.status === "sent" ? `<button class="btn primary" data-do="done">Mark resolved</button><button class="btn" data-do="reopen">Send again</button>`
      : e ? `<button class="btn primary" data-do="send">${A.mode === "compose" ? "Save and open in Gmail" : "Save and send"}</button><button class="btn" data-do="save">Save draft</button><button class="btn ghost" data-do="cancel">Cancel</button>${a.edited ? '<button class="btn ghost" data-do="reset">Reset to original draft</button>' : ""}`
      : `<button class="btn primary" data-do="send" ${a.to ? "" : "disabled title='Add a recipient address first'"}>${A.mode === "compose" ? "Open in Gmail" : A.mode === "dry-run" ? "Send (dry run)" : A.mode === "agentmail" ? "Send" : "Send with Gmail"}</button><button class="btn" data-do="edit">Edit</button>${last && last.event.startsWith("opened in Gmail") ? '<button class="btn" data-do="marksent">Mark as sent</button>' : ""}<span class="spacer"></span><button class="btn ghost" data-do="dismiss">Dismiss</button>`}
    </div>
    <p class="small muted" style="margin:10px 0 0">We need back: ${esc(a.ask)}${a.reply_by ? " · by " + esc(a.reply_by) : ""}</p>
    ${a.history.length ? `<details class="expand"><summary>History (${a.history.length})</summary><ul class="small ink2" style="margin:6px 0 0;padding-left:18px">${a.history.map((h) => `<li>${esc(h.at.replace("T", " ").slice(0, 16))} · ${esc(h.event)}</li>`).join("")}</ul></details>` : ""}
  </div>`;
}

function bindAction(a) {
  const read = () => ({ to: $("#f-to").value.trim(), cc: $("#f-cc").value.trim(), subject: $("#f-subject").value, body: $("#f-body").value });
  const apply = (res) => { if (res.action) A.actions[A.actions.findIndex((x) => x.id === a.id)] = res.action; };
  const run = (p, okMsg) => p.then((res) => { apply(res); ui.editing = false; ui.notice = okMsg ? ["good", okMsg] : null; return res; })
    .catch((err) => { ui.notice = ["bad", err.message]; }).finally(rerender);
  const base = `/api/actions/${a.id}`;
  const handlers = {
    edit: () => { ui.editing = true; ui.notice = null; rerender(); const t = $("#f-to"); if (t && !t.value) t.focus(); else $("#f-body").focus(); },
    cancel: () => { ui.editing = false; ui.notice = null; rerender(); },
    save: () => run(api(base + "/save", read()), "Draft saved."),
    reset: () => run(api(base + "/save", a.draft), "Back to the original draft."),
    send: (btn) => {
      const fields = ui.editing ? read() : {};
      const to = ui.editing ? fields.to : a.to;
      if (A.mode !== "compose" && !confirm(`Send this email to ${to}?`)) return;
      btn.disabled = true; btn.textContent = "Sending…";
      run(api(base + "/send", fields)).then((res) => {
        if (res && res.compose_url) { window.open(res.compose_url, "_blank", "noopener"); ui.notice = ["", "Opened in Gmail. Send it there, then mark it as sent."]; }
        else if (res) { ui.tab = "sent"; ui.sel = a.id; ui.notice = ["good", res.via === "dry-run" ? `Dry run: written to ${res.file}` : `Sent from ${res.from}.`]; }
        rerender();
      });
    },
    marksent: () => { ui.tab = "sent"; run(api(base + "/status", { status: "sent" })); },
    done: () => { ui.tab = "closed"; run(api(base + "/status", { status: "done" })); },
    dismiss: () => run(api(base + "/status", { status: "dismissed" })),
    reopen: () => { ui.tab = "open"; run(api(base + "/status", { status: "open" })); },
  };
  $("#detail").querySelectorAll("[data-do]").forEach((b) => (b.onclick = () => handlers[b.dataset.do](b)));
}

// ------------------------------------------------------------------ boot
Promise.all([
  fetch("data.json", { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
  api("/api/actions").catch(() => null),
]).then(([data, actions]) => {
    D = data;
    A = actions;
    renderNav();
    $("#snapshot").textContent = `Snapshot ${D.snapshot_date} · built ${D.generated_at.replace("T", " ").slice(0, 16)}`;
    addEventListener("hashchange", () => { renderNav(); route(); });
    route();
  })
  .catch((e) => ($("#main").innerHTML = `<div class="empty">Could not load data.json (${esc(e.message)}). Run <code>python3 explorer/build.py</code> and <code>python3 explorer/server.py</code> from the asklio folder.</div>`));
