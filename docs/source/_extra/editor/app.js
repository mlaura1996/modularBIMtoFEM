// The case-study editor: forms generated from schema.json (the sheets of
// core/knowledge_graph/workbook.py), the IFC model in 3D, and saving into the IFC.
import { CASE_FORMAT, readModel, writeCase } from "./step.js";

const $ = id => document.getElementById(id);
const schema = await (await fetch("schema.json")).json();
const SHEETS = Object.keys(schema.sheets);

// ---- state ---------------------------------------------------------------------

let tables = emptyTables();
let model = null;      // {name, text, info, elements: Map(id -> {guid, name, type, materials, psets}), guidToId}
let viewer = null;
let selection = new Set();
let section = "project";
const openCard = {};   // sheet -> index of the open card
let dirty = false;

function emptyTables() { return Object.fromEntries(SHEETS.map(s => [s, []])); }
const columns = sheet => schema.sheets[sheet].map(c => c.name);
const colDef = (sheet, name) => schema.sheets[sheet].find(c => c.name === name);
const keyOf = sheet => sheet === "MasonryTypes" ? "name" : columns(sheet).includes("id") ? "id" : null;
const split = v => String(v || "").split(";").map(x => x.trim()).filter(Boolean);
const join = xs => xs.join("; ");
const words = v => String(v).replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, c => c.toUpperCase())
  .replace(/ ([A-Z])(?=[a-z])/g, (m, c) => " " + c.toLowerCase());
const blankRow = sheet => Object.fromEntries(columns(sheet).map(c => [c, ""]));
const normalise = t => Object.fromEntries(SHEETS.map(s => [s, (t?.[s] || []).map(r => ({ ...blankRow(s), ...r }))]));

function project(key) { return (tables.Project.find(r => r.key === key) || {}).value || ""; }
function setProject(key, value) {
  const r = tables.Project.find(r => r.key === key);
  if (r) r.value = value; else tables.Project.push({ key, value });
}
function ids(sheets) {
  const out = [];
  for (const s of sheets) for (const r of tables[s]) {
    const k = r[keyOf(s)];
    if (k) out.push({ id: k, label: s === "People" || s === "Organisations" ? r.name : s === "MasonryTypes" ? "" : r.label });
  }
  return out;
}
// the records a column may name; "about" may also name the aggregate itself
function refOptions(sheet, name) {
  const opts = ids(colDef(sheet, name).ref);
  if (name === "about" && project("aggregate_id")) opts.unshift({ id: project("aggregate_id"), label: "the aggregate" });
  return opts;
}
function title(sheet, r) {
  if (sheet === "Vulnerabilities") return `${r.facade || "?"}: ${r.vulnerability ? words(r.vulnerability) : "?"}`;
  if (sheet === "Measured") return `${r.masonry_type || "?"}: ${r.quantity ? words(r.quantity) : "?"} ${r.value ? "= " + r.value : ""}`;
  if (sheet === "MasonryTypes") return r.name || "New masonry type";
  return r.label || r.name || r.id || "New record";
}

// ---- small DOM helper --------------------------------------------------------------

// a label tied to the control inside an input (a select, an input in a wrapper, chips)
let uid = 0;
function labelled(text, input) {
  const control = input.matches?.("input, select, textarea") ? input : input.querySelector?.("input, select, textarea");
  const lab = h("label", {}, text);
  if (control) { control.id = control.id && control.id !== "materialNames" ? control.id : `f${++uid}`; lab.htmlFor = control.id; }
  return lab;
}

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}

// ---- sections ------------------------------------------------------------------------

const SECTIONS = [
  { id: "project", title: "Project", sheets: [] },
  { id: "people", title: "People", sheets: ["Organisations", "People"] },
  { id: "activities", title: "Activities", sheets: ["Activities"] },
  { id: "documents", title: "Documents", sheets: ["Documents"] },
  { id: "units", title: "Units & façades", sheets: ["Units", "Facades"] },
  { id: "masonry", title: "Masonry types", sheets: ["MasonryTypes"] },
  { id: "structure", title: "Connections & openings", sheets: ["Connections", "Openings"] },
  { id: "vulnerabilities", title: "Vulnerabilities", sheets: ["Vulnerabilities"] },
  { id: "photos", title: "Photos", sheets: ["Photos"] },
  { id: "measured", title: "Measured", sheets: ["Measured"] },
  { id: "check", title: "Check & save", sheets: [] },
];
const SHEET_TITLES = { Organisations: "Organisations", People: "People", Activities: "Activities", Documents: "Documents",
  Units: "Structural units", Facades: "Façades", MasonryTypes: "Masonry types", Connections: "Connections",
  Openings: "Historic openings", Vulnerabilities: "Vulnerabilities", Photos: "Photographs", Measured: "Measured properties" };
const INTROS = {
  Organisations: "The organisations the people belong to.",
  People: "Everyone who took part in the survey or authored its documents.",
  Activities: "What was done (survey campaigns, scans, tests), when, and by whom. Roles HSV has no class for go in Roles.",
  Documents: "Drawings, point clouds, publications and the BIM model itself, with who made them and in which activity.",
  Units: "The structural units of the aggregate, and what is known about their floors.",
  Facades: "Each façade, or portion of a façade, its unit and its masonry type. Select its walls in the model and assign them here.",
  MasonryTypes: "Each masonry type with the seven parameters of the Masonry Quality Index and the evidence for each. Name it as its IFC material, so the model and the numerical model find it.",
  Connections: "Documented connections between façades: quoins, ties, toothing.",
  Openings: "Historic openings, walled up or altered, of each façade.",
  Vulnerabilities: "The vulnerabilities of each façade wall that enable failure mechanisms (FMO), and what shows them.",
  Photos: "The photographs of each façade. Leave the façade empty for photographs of the whole aggregate.",
  Measured: "Measured properties of a masonry type, compared in the graph with the ones the rules derive.",
};
const LONG = new Set(["description", "notes", "flags", "evidence", "quality", "density_note", "reference_note", "source", "floor_note"]);
const DATETIME = new Set(["start", "end", "taken"]);
const QUANTITIES = ["compressive_strength_MPa", "tensile_strength_MPa", "cohesion_MPa", "young_modulus_MPa",
                    "shear_modulus_MPa", "shear_strength_turnsek_cacovic_MPa", "density_kg_m3"];

function renderTabs() {
  const issues = problems();
  $("tabs").replaceChildren(...SECTIONS.map(s => {
    const n = s.sheets.reduce((a, sh) => a + tables[sh].length, 0);
    const bad = s.id === "check" ? issues.length : 0;
    return h("button", { "aria-current": String(s.id === section), onclick: () => { section = s.id; render(); } },
      s.title, s.sheets.length ? h("span", { class: "count" }, String(n)) : null,
      bad ? h("span", { class: "flag", title: `${bad} to check` }, `● ${bad}`) : null);
  }));
}

function render() {
  renderTabs();
  const s = SECTIONS.find(x => x.id === section);
  const content = $("content");
  if (s.id === "project") content.replaceChildren(projectForm());
  else if (s.id === "check") content.replaceChildren(checkPage());
  else content.replaceChildren(...s.sheets.map(sheetSection));
  paintModel();
}

// ---- forms -------------------------------------------------------------------------------

function changed(rerenderTabs = true) {
  dirty = true;
  $("dirty").hidden = false;
  saveDraft();
  if (rerenderTabs) renderTabs();
}

function projectForm() {
  return h("section", { class: "sheet" },
    h("h2", {}, "Project"),
    h("p", { class: "intro" }, "What the case study is. The namespace is where the IRIs of the graph live; the identifiers below become their local names."),
    h("div", { class: "card open" }, h("div", { class: "body", style: "display:block" },
      h("div", { class: "fields" }, ...schema.project_keys.map(k => {
        const wide = ["title", "description", "namespace", "aggregate_label"].includes(k.name);
        let input;
        if (k.name === "bim_document") {
          input = refSelect(ids(["Documents"]), project(k.name), v => { setProject(k.name, v); changed(); });
        } else if (k.name === "description") {
          input = h("textarea", { rows: 4, oninput: e => { setProject(k.name, e.target.value); changed(false); } });
          input.value = project(k.name);
        } else {
          input = h("input", { type: "text", value: project(k.name),
                               oninput: e => { setProject(k.name, e.target.value); changed(false); } });
        }
        return h("div", { class: "field" + (wide ? " wide" : "") },
          labelled(words(k.name), input), input, h("span", { class: "help" }, k.help));
      })))));
}

function sheetSection(sheet) {
  const rows = tables[sheet];
  return h("section", { class: "sheet" },
    h("h2", {}, SHEET_TITLES[sheet]),
    h("p", { class: "intro" }, INTROS[sheet]),
    h("div", { class: "cards" }, ...rows.map((r, i) => card(sheet, r, i))),
    h("button", { class: "btn add", onclick: () => {
      const r = blankRow(sheet);
      rows.push(r);
      openCard[sheet] = rows.length - 1;
      changed();
      render();
    } }, `+ Add ${SHEET_TITLES[sheet].toLowerCase().replace(/s$/, "").replace(/ie$/, "y")}`));
}

function card(sheet, r, i) {
  const key = keyOf(sheet);
  const isOpen = openCard[sheet] === i;
  const titleEl = h("span", { class: "title" }, title(sheet, r));
  const idEl = key ? h("span", { class: "id" }, r[key] && r[key] !== title(sheet, r) ? r[key] : "") : null;
  const refresh = () => { titleEl.textContent = title(sheet, r); if (idEl) idEl.textContent = r[key] && r[key] !== title(sheet, r) ? r[key] : ""; };
  const el = h("div", { class: "card" + (isOpen ? " open" : "") },
    h("div", { class: "head", onclick: () => { openCard[sheet] = isOpen ? null : i; render(); } },
      h("span", { class: "chev" }, "›"), titleEl, idEl, h("span", { class: "spacer" }),
      sheet === "Facades" && r.elements ? h("span", { class: "id" }, `${split(r.elements).length} elements`) : null,
      h("button", { class: "btn link small", title: "Delete", onclick: e => {
        e.stopPropagation();
        if (!confirm(`Delete “${title(sheet, r)}”?`)) return;
        tables[sheet].splice(i, 1);
        openCard[sheet] = null;
        changed();
        render();
      } }, "Delete")));
  if (isOpen) el.append(h("div", { class: "body" }, h("div", { class: "fields" }, ...fields(sheet, r, refresh))));
  return el;
}

function fields(sheet, r, refresh) {
  if (sheet === "MasonryTypes") {
    const P = schema.parameters;
    const rest = columns(sheet).filter(c => !P.includes(c) && !P.some(p => c === `evidence_${p}`) && c !== "name" && c !== "description");
    return [field(sheet, r, "name", refresh), field(sheet, r, "description", refresh),
      h("div", { class: "mqi" }, h("h3", {}, "Masonry Quality Index parameters, and the evidence for each"),
        ...P.flatMap(p => [field(sheet, r, p, refresh), field(sheet, r, `evidence_${p}`, refresh, true)])),
      ...rest.map(c => field(sheet, r, c, refresh))];
  }
  return columns(sheet).map(c => field(sheet, r, c, refresh));
}

function field(sheet, r, name, refresh, compact = false) {
  const def = colDef(sheet, name);
  const key = keyOf(sheet);
  const set = (v, rerender = false) => { r[name] = v; refresh(); changed(rerender); if (rerender) render(); };
  let input;
  const wide = LONG.has(name) || name.startsWith("evidence") || (name === "label" && ["Documents", "Photos", "Facades"].includes(sheet));
  if (sheet === "Facades" && name === "elements") return elementsField(r);
  if (def.choices) {
    input = h("select", { onchange: e => set(e.target.value) },
      h("option", { value: "" }, "—"),
      ...schema.choices[def.choices].map(v => h("option", { value: v, selected: v === r[name] }, words(v))));
    if (r[name] && !schema.choices[def.choices].includes(r[name])) input.append(h("option", { value: r[name], selected: true }, `${r[name]} (not a category)`));
  } else if (def.ref && name !== "roles") {
    const opts = refOptions(sheet, name).filter(o => !(def.ref.includes(sheet) && o.id === r[key]));
    input = def.many ? chips(opts, split(r[name]), xs => set(join(xs), true))
                     : refSelect(opts, r[name], v => set(v, true));
  } else if (name === "flags") {
    input = h("textarea", { rows: 3, placeholder: "One per line", oninput: e => set(e.target.value) });
    input.value = r[name];
  } else if (LONG.has(name) || name.startsWith("evidence")) {
    input = h("textarea", { rows: 2, oninput: e => set(e.target.value) });
    input.value = r[name];
  } else {
    const attrs = { type: name === "date" ? "date" : "text", value: r[name] };
    if (DATETIME.has(name)) attrs.placeholder = "2023-07-04T16:58:25Z";
    if (name.startsWith("variant_")) attrs.placeholder = "unit_shape=rubble; horizontal_joints=not_continuous";
    if (name === "roles") attrs.placeholder = "PersonId: Role; …";
    input = h("input", attrs);
    if (sheet === "MasonryTypes" && name === "name" && model) {
      const list = h("datalist", { id: "materialNames" }, ...[...new Set(model.info.materials.values())].map(m => h("option", { value: m })));
      input.setAttribute("list", "materialNames");
      input = h("div", {}, input, list);
    }
    if (sheet === "Measured" && name === "quantity") {
      input.setAttribute("list", "quantities");
      input = h("div", {}, input, h("datalist", { id: "quantities" }, ...QUANTITIES.map(q => h("option", { value: q }))));
    }
    if (sheet === "Measured" && name === "basis") {
      input.setAttribute("list", "bases");
      input = h("div", {}, input, h("datalist", { id: "bases" }, h("option", { value: "specimen" }), h("option", { value: "full scale" })));
    }
    const box = input.tagName === "INPUT" ? input : input.querySelector("input");
    box.addEventListener("input", e => set(e.target.value));
    if (name === key) {
      let before = r[name];
      box.addEventListener("focus", () => { before = r[name]; });
      box.addEventListener("change", e => {
        const now = e.target.value.trim();
        if (before && now && before !== now) renameReferences(sheet, before, now);
        render();
      });
    }
    if (name === "label" && key && ["Facades", "Units", "Activities", "Documents", "Connections", "Openings", "Photos"].includes(sheet)) {
      box.addEventListener("change", () => {
        if (!r[key]) { r[key] = uniqueId(sheet, suggestId(sheet, r.label)); changed(); render(); }
      });
    }
  }
  const missing = name === key && !r[name];
  return h("div", { class: "field" + (wide ? " wide" : "") + (missing ? " bad" : "") },
    labelled(name.startsWith("evidence_") ? `Evidence for ${words(name.slice(9)).toLowerCase()}` : name === key ? `${words(name)} (identifier)` : words(name), input),
    input, compact ? null : h("span", { class: "help" }, def.help));
}

function refSelect(opts, value, onchange) {
  const sel = h("select", { onchange: e => onchange(e.target.value) }, h("option", { value: "" }, "—"),
    ...opts.map(o => h("option", { value: o.id, selected: o.id === value }, o.label && o.label !== o.id ? `${o.id} · ${o.label}` : o.id)));
  if (value && !opts.some(o => o.id === value)) sel.append(h("option", { value, selected: true }, `${value} (unknown)`));
  return sel;
}

function chips(opts, values, onchange) {
  const rest = opts.filter(o => !values.includes(o.id));
  return h("div", { class: "chips" },
    ...values.map(v => h("span", { class: "chip" + (opts.some(o => o.id === v) ? "" : " unknown"), title: opts.some(o => o.id === v) ? "" : "Unknown" },
      v, h("button", { "aria-label": `Remove ${v}`, onclick: () => onchange(values.filter(x => x !== v)) }, "×"))),
    rest.length ? h("select", { onchange: e => e.target.value && onchange([...values, e.target.value]) },
      h("option", { value: "" }, "Add…"), ...rest.map(o => h("option", { value: o.id }, o.label && o.label !== o.id ? `${o.id} · ${o.label}` : o.id))) : null);
}

function suggestId(sheet, label) {
  const camel = String(label || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9]+(.)?/g, (m, c) => (c ? c.toUpperCase() : "")).replace(/^./, c => c.toUpperCase()).slice(0, 40);
  const prefix = { Facades: "Facade_", Units: "Unit_" }[sheet] || "";
  return camel ? (camel.startsWith(prefix.slice(0, -1)) ? camel : prefix + camel) : "";
}
function uniqueId(sheet, id) {
  const taken = new Set(tables[sheet].map(r => r[keyOf(sheet)]));
  if (!taken.has(id)) return id;
  let i = 2;
  while (taken.has(`${id}_${i}`)) i++;
  return `${id}_${i}`;
}

function renameReferences(sheet, from, to) {
  for (const s of SHEETS) for (const c of schema.sheets[s]) {
    if (!c.ref || !c.ref.includes(sheet)) continue;
    for (const r of tables[s]) {
      if (c.name === "roles") {
        r.roles = join(split(r.roles).map(x => { const [p, ...rest] = x.split(":"); return p.trim() === from ? `${to}:${rest.join(":")}` : x; }));
      } else if (c.many) r[c.name] = join(split(r[c.name]).map(v => (v === from ? to : v)));
      else if (r[c.name] === from) r[c.name] = to;
    }
  }
  if (sheet === "Documents" && project("bim_document") === from) setProject("bim_document", to);
  changed();
}

// ---- elements of each façade -----------------------------------------------------------------

function facadeOfGuid() {
  const out = new Map();
  for (const f of tables.Facades) for (const g of split(f.elements)) out.set(g, f);
  return out;
}

function assign(facade, guids) {
  for (const f of tables.Facades) f.elements = join(split(f.elements).filter(g => !guids.includes(g)));
  if (facade) facade.elements = join([...split(facade.elements), ...guids]);
  changed();
  render();
}

function elementsField(r) {
  const guids = split(r.elements);
  const sel = [...selection].map(id => model?.elements.get(id)?.guid).filter(Boolean);
  return h("div", { class: "field wide" },
    h("label", {}, "IFC elements"),
    h("div", { class: "elements" },
      h("span", {}, guids.length ? `${guids.length} element${guids.length > 1 ? "s" : ""}` : "None yet"),
      h("button", { class: "btn small", disabled: !model || !sel.length, onclick: () => assign(r, sel),
                    title: model ? "Click walls in the model (Shift or Ctrl to add more), then assign them" : "Open the IFC model first" },
        sel.length ? `Assign the ${sel.length} selected` : "Assign selected"),
      h("button", { class: "btn small", disabled: !model || !guids.length, onclick: () => {
        selection = new Set(guids.map(g => model.guidToId.get(g)).filter(Boolean));
        render();
      } }, "Select in model"),
      h("button", { class: "btn small", disabled: !guids.length, onclick: () => { r.elements = ""; changed(); render(); } }, "Clear")),
    h("span", { class: "help" }, model ? "Select the façade's walls in the model and assign them; they are written into the IFC with this façade, its unit and masonry type."
                                       : "Open the IFC model to assign its elements to this façade."));
}

// ---- the model ---------------------------------------------------------------------------------

const PALETTE = ["#c2703d", "#4f7cac", "#6a9a55", "#a35d9b", "#5c6f7d", "#3f9d9a", "#b0473f", "#7a6bc1", "#8c7a5b", "#d1828f"];

function paintModel() {
  if (!viewer || !model) return;
  const mode = $("colorMode").value;
  const colors = new Map(), legend = [];
  if (mode !== "ifc") {
    const groups = mode === "facade" ? tables.Facades.map(f => [f.id || f.label, split(f.elements)])
      : tables.MasonryTypes.map(t => [t.name, tables.Facades.filter(f => f.masonry_type === t.name).flatMap(f => split(f.elements))]);
    groups.forEach(([name, guids], i) => {
      const c = PALETTE[i % PALETTE.length];
      let n = 0;
      for (const g of guids) { const id = model.guidToId.get(g); if (id) { colors.set(id, c); n++; } }
      legend.push([name, c, n]);
    });
  }
  viewer.setColors(colors, mode !== "ifc");
  viewer.setSelection(selection);
  const lg = $("legend");
  lg.hidden = mode === "ifc" || !legend.length;
  lg.replaceChildren(...legend.map(([name, c, n]) => h("div", {}, h("span", { class: "swatch", style: `background:${c}` }), `${name || "?"} (${n})`)),
    h("div", { class: "muted" }, h("span", { class: "swatch", style: "background:#d9d4cb" }), "not assigned"));
  renderSelection();
}

function renderSelection() {
  const box = $("selbox");
  if (!model || !selection.size) { box.hidden = true; return; }
  box.hidden = false;
  const els = [...selection].map(id => model.elements.get(id)).filter(Boolean);
  const byGuid = facadeOfGuid();
  const facades = [...new Set(els.map(e => byGuid.get(e.guid)?.id || ""))];
  const assignSel = h("select", { onchange: e => {
    const f = tables.Facades.find(f => f.id === e.target.value);
    assign(f || null, els.map(x => x.guid));
  } }, h("option", { value: "" }, "— none —"),
    ...tables.Facades.map(f => h("option", { value: f.id, selected: facades.length === 1 && facades[0] === f.id }, f.label ? `${f.id} · ${f.label}` : f.id)));
  const kids = [h("strong", {}, els.length === 1 ? `${words(els[0].type.replace(/^Ifc/, ""))}` : `${els.length} elements selected`)];
  if (els.length === 1) {
    const e = els[0];
    kids.push(h("dl", {}, h("dt", {}, "Name"), h("dd", {}, e.name || "—"), h("dt", {}, "GlobalId"), h("dd", {}, h("code", {}, e.guid)),
      h("dt", {}, "Material"), h("dd", {}, e.materials.join(", ") || "—"),
      ...(e.psets || []).filter(p => p.name.startsWith("HSV_")).flatMap(p => p.properties.map(q => [h("dt", {}, q.name), h("dd", {}, String(q.value))])).flat()));
  }
  kids.push(h("div", { class: "row" }, labelled("Façade", assignSel), assignSel,
    tables.Facades.length ? null : h("span", { class: "muted" }, "Add façades under Units & façades first."),
    h("button", { class: "btn small", onclick: () => { selection.clear(); render(); } }, "Clear selection")));
  box.replaceChildren(...kids);
}

async function openIfc(name, bytes) {
  busy(`Reading ${name}…`);
  try {
    const text = new TextDecoder().decode(bytes);
    const info = readModel(text);
    if (!viewer) {
      const { Viewer } = await import("./viewer.js");
      viewer = new Viewer($("viewer"), { onPick: (id, add) => {
        if (id === null) { if (!add) selection.clear(); }
        else if (add) selection.has(id) ? selection.delete(id) : selection.add(id);
        else selection = new Set(selection.size === 1 && selection.has(id) ? [] : [id]);
        render();
      } });
    }
    busy("Loading the IFC-Lite engine and the geometry…");
    const { loadGeometry } = await import("./viewer.js");
    const { meshes, products } = await loadGeometry(bytes);
    const elements = new Map(), guidToId = new Map();
    for (const p of products) {
      elements.set(p.expressId, { guid: p.globalId, name: p.name, type: p.type, psets: p.propertySets,
                                  materials: info.materialsOf(p.expressId).map(m => info.materials.get(m)) });
      guidToId.set(p.globalId, p.expressId);
    }
    model = { name, text, info, elements, guidToId };
    viewer.show(meshes);
    selection.clear();
    $("welcome").hidden = true;
    $("viewTools").hidden = $("zoomTools").hidden = false;
    $("saveBtn").disabled = false;
    $("fileName").textContent = name;
    if (info.record?.format === CASE_FORMAT) loadTables(info.record.tables, name);
    else {
      // no case study in the file yet: keep what was entered, to be saved into it
      loadTables(tables, name, SHEETS.some(s => tables[s].length));
      if (!tables.Facades.length) section = "units";
    }
    render();
  } catch (err) {
    console.error(err);
    alert(`Could not open ${name}: ${err.message || err}`);
  } finally { busy(null); }
}

function loadTables(t, name, unsaved = false) {
  tables = normalise(t);
  dirty = unsaved;
  $("dirty").hidden = !unsaved;
  offerDraft(name);
}

function busy(text) {
  $("busy").classList.toggle("on", !!text);
  if (text) $("busyText").textContent = text;
}

// ---- files -------------------------------------------------------------------------------------

async function openFile(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (/\.json$/i.test(file.name)) {
    try {
      const doc = JSON.parse(new TextDecoder().decode(bytes));
      if (doc.format !== CASE_FORMAT) throw new Error("not a case.json written by openBIMtoFEM");
      if (dirty && !confirm("Replace the case study being edited with the one in this file?")) return;
      tables = normalise(doc.tables);
      changed();
      render();
    } catch (err) { alert(`Could not open ${file.name}: ${err.message}`); }
  } else {
    if (dirty && model && !confirm("Open another model? Unsaved changes stay in this browser as a draft.")) return;
    await openIfc(file.name, bytes);
  }
}

function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

const caseDoc = () => ({ format: CASE_FORMAT, version: 1, tables });

function saveIfc() {
  if (!model) return;
  const issues = problems();
  if (issues.length && !confirm(`${issues.length} thing${issues.length > 1 ? "s" : ""} to check (see Check & save). Save anyway?`)) return;
  const PARAM_PROPS = Object.fromEntries(schema.parameters.map(p => [p, p.replace(/(^|_)(.)/g, (m, s, c) => c.toUpperCase())]));
  const elementProps = new Map();
  for (const f of tables.Facades) {
    const vulns = tables.Vulnerabilities.filter(v => v.facade === f.id).map(v => v.vulnerability).filter(Boolean);
    for (const g of split(f.elements)) {
      const id = model.guidToId.get(g);
      if (id) elementProps.set(id, { Facade: f.id, Unit: f.unit, MasonryType: f.masonry_type, Vulnerabilities: join(vulns) });
    }
  }
  const materialProps = new Map();
  for (const [id, name] of model.info.materials) {
    const t = tables.MasonryTypes.find(t => t.name === name);
    if (!t) continue;
    materialProps.set(id, { ...Object.fromEntries(schema.parameters.map(p => [PARAM_PROPS[p], t[p]])),
                            MassDensity: t.density_kg_m3 });
  }
  const out = writeCase(model.text, caseDoc(), elementProps, materialProps);
  download(model.name, out, "application/x-step");
  model.text = out;
  model.info = readModel(out);
  dirty = false;
  $("dirty").hidden = true;
  clearDraft();
}

// ---- draft kept in this browser -------------------------------------------------------------------

const draftKey = () => `obf-case-editor:${model?.name || "no-model"}`;
let draftTimer = null;
function saveDraft() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    try { localStorage.setItem(draftKey(), JSON.stringify({ at: new Date().toISOString(), tables })); } catch { /* storage unavailable */ }
  }, 600);
}
function clearDraft() { try { localStorage.removeItem(draftKey()); } catch { /* storage unavailable */ } }
function offerDraft(name) {
  let draft = null;
  try { draft = JSON.parse(localStorage.getItem(`obf-case-editor:${name || "no-model"}`) || "null"); } catch { draft = null; }
  const banner = $("draftBanner");
  if (!draft || JSON.stringify(normalise(draft.tables)) === JSON.stringify(tables)) { banner.hidden = true; return; }
  $("draftText").textContent = `Unsaved changes to ${name || "this case study"} from ${new Date(draft.at).toLocaleString()} are kept in this browser.`;
  banner.hidden = false;
  $("draftRestore").onclick = () => { tables = normalise(draft.tables); changed(); banner.hidden = true; render(); };
  $("draftDiscard").onclick = () => { clearDraft(); banner.hidden = true; };
}

// ---- checks ------------------------------------------------------------------------------------------

function problems() {
  const out = [];
  const known = Object.fromEntries(SHEETS.map(s => [s, new Set(tables[s].map(r => r[keyOf(s)]).filter(Boolean))]));
  for (const s of SHEETS) {
    const key = keyOf(s);
    if (key) {
      const seen = new Set();
      tables[s].forEach((r, i) => {
        if (!r[key]) out.push([s, i, `${SHEET_TITLES[s]}: “${title(s, r)}” has no ${key === "name" ? "name" : "identifier"}`]);
        else if (/\s/.test(r[key])) out.push([s, i, `${SHEET_TITLES[s]}: the identifier “${r[key]}” contains spaces`]);
        else if (seen.has(r[key])) out.push([s, i, `${SHEET_TITLES[s]}: “${r[key]}” is used twice`]);
        seen.add(r[key]);
      });
    }
    for (const c of schema.sheets[s]) {
      tables[s].forEach((r, i) => {
        if (c.ref) {
          const vals = c.name === "roles" ? split(r.roles).map(x => x.split(":")[0].trim()) : c.many ? split(r[c.name]) : [r[c.name]];
          for (const v of vals) if (v && !c.ref.some(t => known[t].has(v)) && !(c.name === "about" && v === project("aggregate_id")))
            out.push([s, i, `${SHEET_TITLES[s]}: “${title(s, r)}” refers to ${words(c.name).toLowerCase()} “${v}”, which does not exist`]);
        }
        if (c.choices && r[c.name] && !schema.choices[c.choices].includes(r[c.name]))
          out.push([s, i, `${SHEET_TITLES[s]}: “${title(s, r)}” has “${r[c.name]}”, not a value of ${words(c.name).toLowerCase()}`]);
      });
    }
  }
  tables.Facades.forEach((f, i) => {
    if (!f.unit) out.push(["Facades", i, `Façades: “${title("Facades", f)}” has no unit`]);
    if (!f.masonry_type) out.push(["Facades", i, `Façades: “${title("Facades", f)}” has no masonry type`]);
  });
  tables.MasonryTypes.forEach((t, i) => {
    const missing = schema.parameters.filter(p => !t[p]);
    if (missing.length) out.push(["MasonryTypes", i, `Masonry types: “${t.name || "?"}” has no ${missing.map(words).map(x => x.toLowerCase()).join(", ")}`]);
    if (t.density_kg_m3 === "" || isNaN(+t.density_kg_m3)) out.push(["MasonryTypes", i, `Masonry types: “${t.name || "?"}” needs a mass density (a number)`]);
  });
  tables.Vulnerabilities.forEach((v, i) => { if (!v.facade || !v.vulnerability) out.push(["Vulnerabilities", i, "Vulnerabilities: a row needs a façade and a vulnerability"]); });
  tables.Measured.forEach((m, i) => { if (m.value === "" || isNaN(+m.value)) out.push(["Measured", i, `Measured: “${title("Measured", m)}” needs a numeric value`]); });
  for (const k of ["id", "title", "namespace", "aggregate_id", "aggregate_label"])
    if (!project(k)) out.push(["Project", null, `Project: ${words(k).toLowerCase()} is empty`]);
  return out;
}

function checkPage() {
  const issues = problems();
  const sectionOf = sheet => SECTIONS.find(s => s.sheets.includes(sheet))?.id || "project";
  const unassigned = model ? [...model.elements.values()].filter(e => /Wall/.test(e.type) && !facadeOfGuid().has(e.guid)).length : 0;
  return h("section", { class: "sheet" },
    h("h2", {}, "Check & save"),
    h("p", { class: "intro" }, "What the knowledge graph cannot be built without, or would build wrong. Click a line to go to it."),
    h("ul", { class: "problems" },
      ...(issues.length ? issues.map(([sheet, i, msg]) => h("li", { style: "cursor:pointer", onclick: () => {
        section = sectionOf(sheet); if (i !== null) openCard[sheet] = i; render();
      } }, msg)) : [h("li", { class: "ok" }, "Everything refers to something that exists.")]),
      model && unassigned ? h("li", { class: "warn" }, `${unassigned} wall${unassigned > 1 ? "s" : ""} of the model belong${unassigned > 1 ? "" : "s"} to no façade.`) : null),
    h("h2", { style: "margin-top:20px" }, "Save"),
    h("p", {}, model ? h("span", {}, h("strong", {}, "Save IFC"), " downloads ", h("code", {}, model.name),
        " with the case study in it: the whole record on the IfcProject (property set ", h("code", {}, "HSV_CaseRecord"),
        "), the façade, unit, masonry type and vulnerabilities on each assigned element (", h("code", {}, "HSV_Facade"),
        "), and the MQI parameters on each IfcMaterial named as a masonry type (", h("code", {}, "HMO_MasonryQuality"), ").")
      : "Open the IFC model to save the case study into it. Without a model, download the case.json."),
    h("div", { class: "row", style: "display:flex;gap:8px;flex-wrap:wrap" },
      h("button", { class: "btn primary", disabled: !model, onclick: saveIfc }, "Save IFC"),
      h("button", { class: "btn", onclick: () => download("case.json", JSON.stringify(caseDoc(), null, 1), "application/json") }, "Download case.json")),
    h("h2", { style: "margin-top:20px" }, "Build the knowledge graph"),
    h("p", {}, "With openBIMtoFEM installed (Java and owlready2 for the reasoner):"),
    h("pre", {}, `python -m core.knowledge_graph build ${model ? model.name : "case.json"} --out output/<case>`));
}

// ---- start -----------------------------------------------------------------------------------------------

$("openBtn").onclick = $("welcomeOpen").onclick = () => $("fileInput").click();
$("fileInput").onchange = e => { const f = e.target.files[0]; e.target.value = ""; if (f) openFile(f); };
$("saveBtn").onclick = saveIfc;
$("jsonBtn").onclick = () => download("case.json", JSON.stringify(caseDoc(), null, 1), "application/json");
$("colorMode").onchange = paintModel;
$("zoomIn").onclick = () => viewer?.zoom(0.8);
$("zoomOut").onclick = () => viewer?.zoom(1.25);
$("zoomFit").onclick = () => viewer?.fit();
$("exampleBtn").onclick = async () => {
  busy("Downloading the example…");
  const bytes = new Uint8Array(await (await fetch("examples/sera_aims_aggregate_1.ifc")).arrayBuffer());
  await openIfc("sera_aims_aggregate_1.ifc", bytes);
};
addEventListener("dragover", e => e.preventDefault());
addEventListener("drop", e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) openFile(f); });
addEventListener("beforeunload", e => { if (dirty) e.preventDefault(); });
// for scripted tests of the page
window.caseEditor = { get viewer() { return viewer; }, get model() { return model; }, get tables() { return tables; },
                      get selection() { return selection; } };
offerDraft(null);
render();
if (new URLSearchParams(location.search).get("example") === "sera-aims") $("exampleBtn").click();
