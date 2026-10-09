// Reading and writing the case study in an IFC (STEP) file.
//
// The case study is stored as (core/knowledge_graph/ifc_record.py reads it back):
//   IfcProject   property set HSV_CaseRecord: Record (the tables, as JSON), Format, Modified
//   elements     property set HSV_Facade: Facade, Unit, MasonryType, Vulnerabilities
//   IfcMaterial  material properties HMO_MasonryQuality: the seven MQI categories, MassDensity
// Saving removes what an earlier save wrote and writes it again, so the file
// never holds two versions; every other entity is left byte for byte as it was.

export const CASE_FORMAT = "openbimtofem-case";
const OUR_PSETS = new Set(["HSV_CaseRecord", "HSV_Facade"]);
const OUR_MATERIAL_PROPS = "HMO_MasonryQuality";

// ---- strings ---------------------------------------------------------------

export function encodeString(s) {
  let out = "";
  for (const ch of String(s)) {
    const c = ch.codePointAt(0);
    if (ch === "'") out += "''";
    else if (ch === "\\") out += "\\\\";
    else if (c >= 0x20 && c <= 0x7e) out += ch;
    else {
      let hex = "";
      for (let i = 0; i < ch.length; i++) hex += ch.charCodeAt(i).toString(16).toUpperCase().padStart(4, "0");
      out += "\\X2\\" + hex + "\\X0\\";
    }
  }
  return out;
}

export function decodeString(s) {
  let out = "", i = 0;
  while (i < s.length) {
    if (s.startsWith("''", i)) { out += "'"; i += 2; }
    else if (s.startsWith("\\\\", i)) { out += "\\"; i += 2; }
    else if (s.startsWith("\\X2\\", i) || s.startsWith("\\X4\\", i)) {
      const width = s[i + 2] === "2" ? 4 : 8, end = s.indexOf("\\X0\\", i + 4);
      const hex = s.slice(i + 4, end);
      for (let k = 0; k < hex.length; k += width) {
        const u = parseInt(hex.slice(k, k + width), 16);
        out += width === 8 ? String.fromCodePoint(u) : String.fromCharCode(u);
      }
      i = end + 4;
    } else if (s.startsWith("\\X\\", i)) { out += String.fromCharCode(parseInt(s.slice(i + 3, i + 5), 16)); i += 5; }
    else if (s.startsWith("\\S\\", i)) { out += String.fromCharCode(s.charCodeAt(i + 3) + 128); i += 4; }
    else { out += s[i]; i += 1; }
  }
  return out;
}

const real = x => {
  let s = String(+x).toUpperCase();
  if (!/[.E]/.test(s)) s += ".";
  else if (s.includes("E") && !s.includes(".")) s = s.replace("E", ".E");
  return s;
};

// ---- parsing ---------------------------------------------------------------

// Every entity of the DATA section: id -> {type, args, start, end}, where
// start..end is the span of "#id=TYPE(...);" in the text.
export function parseEntities(text) {
  const entities = new Map();
  const data = text.indexOf("DATA;");
  const re = /#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(/g;
  re.lastIndex = data < 0 ? 0 : data;
  const n = text.length;
  let m;
  while ((m = re.exec(text))) {
    let j = re.lastIndex, depth = 1;
    while (j < n && depth) {
      const c = text[j];
      if (c === "'") {
        j++;
        while (j < n && !(text[j] === "'" && text[j + 1] !== "'")) j += text[j] === "'" ? 2 : 1;
      } else if (c === "(") depth++;
      else if (c === ")") depth--;
      j++;
    }
    const args = text.slice(re.lastIndex, j - 1);
    while (j < n && text[j] !== ";") j++;
    entities.set(+m[1], { type: m[2].toUpperCase(), args, start: m.index, end: j + 1 });
    re.lastIndex = j + 1;
  }
  return entities;
}

// Top-level arguments: strings decoded, "#12" references, arrays for lists,
// {type, value} for typed values (IFCLABEL('x')), other tokens as text.
export function parseArgs(args) {
  let pos = 0;
  const ws = () => { while (pos < args.length && " \r\n\t".includes(args[pos])) pos++; };
  function value() {
    ws();
    const c = args[pos];
    if (c === "'") {
      let j = pos + 1;
      while (!(args[j] === "'" && args[j + 1] !== "'")) j += args[j] === "'" ? 2 : 1;
      const s = decodeString(args.slice(pos + 1, j));
      pos = j + 1;
      return s;
    }
    if (c === "(") {
      pos++;
      const items = [];
      for (;;) {
        while (" \r\n\t,".includes(args[pos])) pos++;
        if (args[pos] === ")") { pos++; return items; }
        items.push(value());
      }
    }
    const typed = /^[A-Za-z0-9_]+\s*\(/.exec(args.slice(pos, pos + 80));
    if (typed) {
      pos += typed[0].length;
      const v = value();
      while (args[pos] !== ")") pos++;
      pos++;
      return { type: typed[0].slice(0, -1).trim().toUpperCase(), value: v };
    }
    const tok = /^[^,()]+/.exec(args.slice(pos));
    pos += tok[0].length;
    return tok[0].trim();
  }
  const out = [];
  while (pos < args.length) {
    while (pos < args.length && " \r\n\t,".includes(args[pos])) pos++;
    if (pos < args.length) out.push(value());
  }
  return out;
}

const refId = r => (typeof r === "string" && r.startsWith("#") ? +r.slice(1) : null);

// ---- reading the model -------------------------------------------------------

// What the editor needs from the file: schema, project, materials, the
// materials of every element (directly, through its layers or constituents,
// or through its type), and the case record if one was saved.
export function readModel(text) {
  const ents = parseEntities(text);
  const schema = (/FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'/i.exec(text) || [])[1] || "IFC4";
  const args = id => parseArgs(ents.get(id).args);
  const materials = new Map();     // IfcMaterial id -> name
  let project = null, ownerHistory = null, record = null;
  for (const [id, e] of ents) {
    if (e.type === "IFCMATERIAL") materials.set(id, args(id)[0]);
    else if (e.type === "IFCPROJECT") project = id;
    else if (e.type === "IFCOWNERHISTORY" && ownerHistory === null) ownerHistory = id;
  }
  // IfcMaterial ids reachable from a material definition
  const reach = (id, depth = 0, out = new Set()) => {
    const e = ents.get(id);
    if (!e || depth > 5) return out;
    if (e.type === "IFCMATERIAL") { out.add(id); return out; }
    const walk = v => Array.isArray(v) ? v.forEach(walk) : (refId(v) !== null && reach(refId(v), depth + 1, out));
    parseArgs(e.args).forEach(walk);
    return out;
  };
  const direct = new Map(), byType = new Map(), typeOf = new Map();
  for (const [id, e] of ents) {
    if (e.type === "IFCRELASSOCIATESMATERIAL") {
      const a = args(id), mats = [...reach(refId(a[5]))];
      for (const r of a[4]) direct.set(refId(r), mats);
    } else if (e.type === "IFCRELDEFINESBYTYPE") {
      const a = args(id);
      for (const r of a[4]) typeOf.set(refId(r), refId(a[5]));
    }
  }
  for (const [obj, mats] of direct) byType.set(obj, mats);
  const materialsOf = id => direct.get(id) || byType.get(typeOf.get(id)) || [];
  // the case record
  for (const [id, e] of ents) {
    if (e.type !== "IFCPROPERTYSET" || !e.args.includes("'HSV_CaseRecord'")) continue;
    for (const r of args(id)[4]) {
      const p = args(refId(r));
      if (p[0] === "Record") {
        try { record = JSON.parse(p[2].value); } catch { record = null; }
      }
    }
  }
  return { schema: schema.toUpperCase(), project, ownerHistory, materials, materialsOf, record, entities: ents };
}

// ---- writing -----------------------------------------------------------------

const GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";
export function newGuid() {
  const r = crypto.getRandomValues(new Uint8Array(22));
  return GUID_CHARS[r[0] % 4] + Array.from(r.slice(1), b => GUID_CHARS[b % 64]).join("");
}

const label = v => `IFCLABEL('${encodeString(String(v).slice(0, 255))}')`;
const textValue = v => `IFCTEXT('${encodeString(v)}')`;

// text: the IFC file as read. caseDoc: {format, version, tables}.
// elementProps: Map(expressId -> {Facade, Unit, MasonryType, Vulnerabilities}).
// materialProps: Map(IfcMaterial id -> {UnitDimensions: ..., MassDensity: number}).
export function writeCase(text, caseDoc, elementProps, materialProps) {
  const model = readModel(text);
  const ents = model.entities;
  const ifc2x3 = model.schema.startsWith("IFC2X3");
  // what an earlier save wrote
  const remove = new Set(), ourSets = new Set();
  for (const [id, e] of ents) {
    if (e.type === "IFCPROPERTYSET" || e.type === "IFCMATERIALPROPERTIES" || e.type === "IFCEXTENDEDMATERIALPROPERTIES") {
      const a = parseArgs(e.args);
      const name = e.type === "IFCPROPERTYSET" ? a[2] : e.type === "IFCMATERIALPROPERTIES" ? a[0] : a[3];
      const props = e.type === "IFCPROPERTYSET" ? a[4] : e.type === "IFCMATERIALPROPERTIES" ? a[2] : a[1];
      if (OUR_PSETS.has(name) || name === OUR_MATERIAL_PROPS) {
        remove.add(id); ourSets.add(id);
        for (const r of props || []) remove.add(refId(r));
      }
    }
  }
  for (const [id, e] of ents) {
    if (e.type === "IFCRELDEFINESBYPROPERTIES" && ourSets.has(refId(parseArgs(e.args)[5]))) remove.add(id);
  }
  let maxId = 0;
  for (const id of ents.keys()) maxId = Math.max(maxId, id);
  let next = maxId + 1;
  const oh = model.ownerHistory ? `#${model.ownerHistory}` : "$";
  const lines = [];
  const emit = body => { const id = next++; lines.push(`#${id}=${body};`); return id; };
  const props = obj => Object.entries(obj).filter(([, v]) => v !== "" && v !== null && v !== undefined)
    .map(([k, v]) => emit(`IFCPROPERTYSINGLEVALUE('${encodeString(k)}',$,${
      typeof v === "object" ? v.step : typeof v === "number" ? `IFCREAL(${real(v)})` : label(v)},$)`));
  const pset = (target, name, obj) => {
    const ps = props(obj);
    if (!ps.length) return;
    const set = emit(`IFCPROPERTYSET('${newGuid()}',${oh},'${name}',$,(${ps.map(p => "#" + p).join(",")}))`);
    emit(`IFCRELDEFINESBYPROPERTIES('${newGuid()}',${oh},$,$,(#${target}),#${set})`);
  };
  if (model.project !== null) {
    pset(model.project, "HSV_CaseRecord", {
      Record: { step: textValue(JSON.stringify(caseDoc)) },
      Format: `${CASE_FORMAT}/${caseDoc.version}`,
      Modified: new Date().toISOString().slice(0, 19) + "Z",
    });
  }
  for (const [id, obj] of elementProps) if (ents.has(id)) pset(id, "HSV_Facade", obj);
  for (const [id, obj] of materialProps) {
    if (!ents.has(id)) continue;
    const step = Object.fromEntries(Object.entries(obj).map(([k, v]) =>
      [k, k === "MassDensity" && v !== "" && !isNaN(+v) ? { step: `IFCMASSDENSITYMEASURE(${real(v)})` } : v]));
    const ps = props(step);
    if (!ps.length) continue;
    const list = `(${ps.map(p => "#" + p).join(",")})`;
    emit(ifc2x3 ? `IFCEXTENDEDMATERIALPROPERTIES(#${id},${list},$,'${OUR_MATERIAL_PROPS}')`
                : `IFCMATERIALPROPERTIES('${OUR_MATERIAL_PROPS}',$,${list},#${id})`);
  }
  // the file without the removed entities, the new ones before ENDSEC of DATA
  const spans = [...remove].filter(id => ents.has(id)).map(id => ents.get(id)).sort((a, b) => a.start - b.start);
  let out = "", pos = 0;
  for (const s of spans) {
    out += text.slice(pos, s.start);
    pos = s.end;
    if (text[pos] === "\r") pos++;
    if (text[pos] === "\n") pos++;
  }
  out += text.slice(pos);
  const dataAt = out.indexOf("DATA;");
  const endsec = out.indexOf("ENDSEC;", dataAt);
  const nl = out.includes("\r\n") ? "\r\n" : "\n";
  return out.slice(0, endsec) + lines.join(nl) + (lines.length ? nl : "") + out.slice(endsec);
}
