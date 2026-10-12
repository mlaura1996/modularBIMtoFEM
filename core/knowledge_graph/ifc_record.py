"""The case study as the editor stores it in an IFC file, read back, and the
derived properties written back into the file.

The editor (docs/source/_extra/editor) writes the case study into the IFC
model it was entered on:

    IfcProject   property set HSV_CaseRecord: Record, the whole case study
                 as JSON (the tables of the workbook, see workbook.py)
    elements     property set HSV_Facade: Facade, Unit, MasonryType and
                 Vulnerabilities of the facade the element belongs to
    IfcMaterial  material properties HMO_MasonryQuality: the seven MQI
                 categories and the mass density of the masonry type of
                 the same name

The record is the source; the element and material property sets repeat
it where other IFC software can see it. Reading needs only the record, so
this module is a minimal STEP reader with no dependency.

After the reasoning, write_material_properties() writes the properties
derived for each masonry type back into the IFC file, on the IfcMaterial of
the same name, in the property sets the conversion to the numerical model
reads and the Information Delivery Specification requires:

    Pset_MaterialCommon      MassDensity, MaterialModelType
    Pset_MaterialMechanical  YoungModulus, ShearModulus, PoissonRatio,
                             CompressiveStrength, TensileStrength,
                             ShearStrength, isStructural, ConstitutiveModel
    Pset_MaterialSource      Source (how the values were derived)

The moduli and strengths are written in MPa, the unit
core/ifc_processing/data_extractor.py reads them in, so the file is given
N/mm2 as its modulus unit and MPa as its pressure unit when it declares
none; a file that declares other units is refused rather than mixed.
"""
import json
import re

ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(")


def entities(text):
    """(id, TYPE, argument text) of every entity of a STEP file."""
    for eid, kind, args, _, _ in spans(text):
        yield eid, kind, args


def spans(text):
    """(id, TYPE, argument text, start, end) of every entity, where
    text[start:end] is the whole "#id=TYPE(...);"."""
    i = text.find("DATA;") + 5 if "DATA;" in text else 0
    n = len(text)
    while True:
        m = ENTITY.search(text, i)
        if not m:
            return
        j, depth = m.end(), 1
        while j < n and depth:
            c = text[j]
            if c == "'":                      # string: '' is an escaped quote
                j += 1
                while j < n and not (text[j] == "'" and text[j + 1:j + 2] != "'"):
                    j += 2 if text[j] == "'" else 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        args = text[m.end():j - 1]
        while j < n and text[j] != ";":
            j += 1
        yield int(m.group(1)), m.group(2).upper(), args, m.start(), j + 1
        i = j + 1


def arguments(args):
    """The top-level arguments: str for strings, '#12' references, lists,
    ('IFCTEXT', value) for typed values, other tokens as text."""
    pos = 0

    def value():
        nonlocal pos
        while args[pos] in " \r\n\t":
            pos += 1
        c = args[pos]
        if c == "'":
            j = pos + 1
            while not (args[j] == "'" and args[j + 1:j + 2] != "'"):
                j += 2 if args[j] == "'" else 1
            out, pos = decode(args[pos + 1:j]), j + 1
            return out
        if c == "(":
            pos += 1
            items = []
            while True:
                while args[pos] in " \r\n\t,":
                    pos += 1
                if args[pos] == ")":
                    pos += 1
                    return items
                items.append(value())
        m = re.compile(r"[A-Za-z0-9_]+\s*\(").match(args, pos)
        if m:                                  # typed value, e.g. IFCTEXT('...')
            pos = m.end()
            inner = value()
            while args[pos] != ")":
                pos += 1
            pos += 1
            return (m.group(0)[:-1].strip().upper(), inner)
        m = re.compile(r"[^,()]+").match(args, pos)
        pos = m.end()
        return m.group(0).strip()

    out = []
    while pos < len(args):
        while pos < len(args) and args[pos] in " \r\n\t,":
            pos += 1
        if pos < len(args):
            out.append(value())
    return out


def decode(s):
    """A STEP string literal (without its quotes) as text."""
    out, i = [], 0
    while i < len(s):
        if s.startswith("''", i):
            out.append("'"); i += 2
        elif s.startswith("\\\\", i):
            out.append("\\"); i += 2
        elif s.startswith("\\X2\\", i) or s.startswith("\\X4\\", i):
            width = 4 if s[i + 2] == "2" else 8
            end = s.index("\\X0\\", i + 4)
            hexs = s[i + 4:end]
            units = [int(hexs[k:k + width], 16) for k in range(0, len(hexs), width)]
            out.append("".join(chr(u) for u in units) if width == 8
                       else bytes(b for u in units for b in u.to_bytes(2, "big")).decode("utf-16-be"))
            i = end + 4
        elif s.startswith("\\X\\", i):
            out.append(chr(int(s[i + 3:i + 5], 16))); i += 5
        elif s.startswith("\\S\\", i):
            out.append(chr(ord(s[i + 3]) + 128)); i += 4
        else:
            out.append(s[i]); i += 1
    return "".join(out)


def read_record(path):
    """The case study the editor wrote into an IFC file, or None."""
    text = open(path, encoding="utf-8", errors="replace").read()
    if "HSV_CaseRecord" not in text:
        return None
    raw = {}
    for eid, kind, args in entities(text):
        if kind in ("IFCPROPERTYSET", "IFCPROPERTYSINGLEVALUE"):
            raw[eid] = (kind, args)
    for eid, (kind, args) in raw.items():
        if kind != "IFCPROPERTYSET":
            continue
        a = arguments(args)
        if a[2] != "HSV_CaseRecord":
            continue
        for ref in a[4]:
            pa = arguments(raw[int(ref[1:])][1])
            if pa[0] == "Record":
                return json.loads(pa[2][1])
    return None


# ---------------------------------------------------------------- writing ----

def encode(s):
    """Text as the body of a STEP string literal."""
    out = []
    for ch in str(s):
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 0x20 <= ord(ch) <= 0x7E:
            out.append(ch)
        else:
            out.append("\\X2\\" + ch.encode("utf-16-be").hex().upper() + "\\X0\\")
    return "".join(out)


def real(x):
    """A STEP REAL, which always carries a decimal point."""
    s = repr(float(x)).upper()
    mantissa = s.split("E")[0]
    if "." not in mantissa:
        s = s.replace(mantissa, mantissa + ".", 1)
    return s


MATERIAL_PSETS = ("Pset_MaterialCommon", "Pset_MaterialMechanical", "Pset_MaterialSource")


def material_properties(entry):
    """The three property sets of one masonry type of the material database,
    as {pset: [(property, STEP value)]}."""
    t = entry.get("_mqi_total", {})
    source = ("Derived by the openBIMtoFEM knowledge-graph builder from the case study recorded in this file. "
              "Masonry Quality Index (vertical {v}, out of plane {o}, in plane {i}) and homogenised properties "
              "from the HMO rules, run by Pellet and cross-checked with core/ifc_processing/hmo_mqi.py. The "
              "Poisson ratio and the tensile strength are assumptions of the material engine, not HMO results."
              ).format(v=t.get("vertical", "?"), o=t.get("out_of_plane", "?"), i=t.get("in_plane", "?"))
    model = entry.get("material_model_type") or "PlasticDamage"
    mech = [("YoungModulus", f"IFCMODULUSOFELASTICITYMEASURE({real(entry['young_modulus'])})")]
    if "_shear_modulus_MPa" in entry:
        mech.append(("ShearModulus", f"IFCMODULUSOFELASTICITYMEASURE({real(entry['_shear_modulus_MPa'])})"))
    mech += [("PoissonRatio", f"IFCPOSITIVERATIOMEASURE({real(entry['poisson_ratio'])})"),
             ("CompressiveStrength", f"IFCPRESSUREMEASURE({real(entry['compressive_strength'])})"),
             ("TensileStrength", f"IFCPRESSUREMEASURE({real(entry['tensile_strength'])})")]
    if "_shear_strength_turnsek_cacovic_MPa" in entry:
        mech.append(("ShearStrength", f"IFCPRESSUREMEASURE({real(entry['_shear_strength_turnsek_cacovic_MPa'])})"))
    mech += [("isStructural", "IFCBOOLEAN(.T.)"), ("ConstitutiveModel", f"IFCLABEL('{encode(model)}')")]
    return {"Pset_MaterialCommon": [("MassDensity", f"IFCMASSDENSITYMEASURE({real(entry['density'])})"),
                                    ("MaterialModelType", f"IFCLABEL('{encode(model)}')")],
            "Pset_MaterialMechanical": mech,
            "Pset_MaterialSource": [("Source", f"IFCTEXT('{encode(source)}')")]}


def _unit_assignment(index):
    """Id of the unit assignment, its unit ids, and those units by unit type."""
    ua = next(eid for eid, (kind, _, _, _) in index.items() if kind == "IFCUNITASSIGNMENT")
    refs = [int(r[1:]) for r in arguments(index[ua][1])[0]]
    by_type = {}
    for r in refs:
        a = arguments(index[r][1])
        if len(a) > 1 and isinstance(a[1], str) and a[1].startswith("."):
            by_type[a[1].strip(".")] = r
    return ua, refs, by_type


def write_material_properties(src, dst, database):
    """Writes the derived properties of each masonry type of `database` (the
    material database the builder writes) on the IfcMaterial of the same name
    of the IFC file `src`, into `dst`. Property sets of the same names that an
    earlier run wrote on those materials are replaced; every other entity of
    the file is left as it was. Returns the names of the materials written."""
    text = open(src, encoding="utf-8", errors="replace").read()
    index = {eid: (kind, args, a, b) for eid, kind, args, a, b in spans(text)}
    schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    ifc2x3 = bool(schema) and schema.group(1).upper().startswith("IFC2X3")
    materials = {arguments(args)[0]: eid for eid, (kind, args, _, _) in index.items() if kind == "IFCMATERIAL"}
    targets = {name: materials[name] for name in database if name in materials}
    target_ids = set(targets.values())

    remove = set()
    for eid, (kind, args, _, _) in index.items():
        if kind in ("IFCMATERIALPROPERTIES", "IFCEXTENDEDMATERIALPROPERTIES"):
            a = arguments(args)
            name, props, mat = (a[0], a[2], a[3]) if kind == "IFCMATERIALPROPERTIES" else (a[3], a[1], a[0])
            if name in MATERIAL_PSETS and int(mat[1:]) in target_ids:
                remove.add(eid)
                remove.update(int(r[1:]) for r in props)

    next_id = max(index) + 1
    lines = []

    def emit(body):
        nonlocal next_id
        lines.append(f"#{next_id}={body};")
        next_id += 1
        return next_id - 1

    def unit_name(uid):
        return tuple(arguments(index[uid][1])[2:4]) if uid in index else None

    # units: N/mm2 for the moduli, MPa for the strengths, kg/m3 (the default) for the density
    ua, refs, by_type = _unit_assignment(index)
    added = []
    mod = by_type.get("MODULUSOFELASTICITYUNIT")
    if mod is not None:
        dims = sorted((unit_name(int(arguments(index[int(e[1:])][1])[0][1:])), arguments(index[int(e[1:])][1])[1])
                      for e in arguments(index[mod][1])[0])
        if dims != sorted([(("$", ".NEWTON."), "1"), ((".MILLI.", ".METRE."), "-2")]):
            raise ValueError(f"{src}: the modulus unit is not N/mm2 {dims}; not mixing units")
    else:
        newton = by_type.get("FORCEUNIT")
        if newton is None or unit_name(newton) != ("$", ".NEWTON."):
            newton = emit("IFCSIUNIT(*,.FORCEUNIT.,$,.NEWTON.)")
            if "FORCEUNIT" not in by_type:
                added.append(newton)
        mm = emit("IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)")
        e1 = emit(f"IFCDERIVEDUNITELEMENT(#{newton},1)")
        e2 = emit(f"IFCDERIVEDUNITELEMENT(#{mm},-2)")
        added.append(emit(f"IFCDERIVEDUNIT((#{e1},#{e2}),.MODULUSOFELASTICITYUNIT.,$)"))
    pres = by_type.get("PRESSUREUNIT")
    if pres is not None:
        if unit_name(pres) != (".MEGA.", ".PASCAL."):
            raise ValueError(f"{src}: the pressure unit is not MPa; not mixing units")
    else:
        added.append(emit("IFCSIUNIT(*,.PRESSUREUNIT.,.MEGA.,.PASCAL.)"))
    if "MASSDENSITYUNIT" in by_type:
        raise ValueError(f"{src}: declares its own mass density unit; densities are written in kg/m3")

    for name, mid in targets.items():
        for pset, props in material_properties(database[name]).items():
            ids = ",".join(f"#{emit(f'IFCPROPERTYSINGLEVALUE({chr(39)}{encode(k)}{chr(39)},$,{v},$)')}"
                           for k, v in props)
            emit(f"IFCEXTENDEDMATERIALPROPERTIES(#{mid},({ids}),$,'{pset}')" if ifc2x3
                 else f"IFCMATERIALPROPERTIES('{pset}',$,({ids}),#{mid})")

    # removed entities out, the unit assignment extended, new entities before ENDSEC
    out, pos = [], 0
    for eid in sorted(remove | ({ua} if added else set()), key=lambda e: index[e][2]):
        _, _, a, b = index[eid]
        out.append(text[pos:a])
        pos = b
        if eid == ua:
            out.append(f"#{ua}=IFCUNITASSIGNMENT(({','.join(f'#{r}' for r in refs + added)}));")
        else:
            while pos < len(text) and text[pos] in "\r\n":
                pos += 1
    out.append(text[pos:])
    body = "".join(out)
    nl = "\r\n" if "\r\n" in body else "\n"
    endsec = body.index("ENDSEC;", body.index("DATA;"))
    body = body[:endsec] + nl.join(lines) + nl + body[endsec:]
    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    return sorted(targets)
