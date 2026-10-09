"""The case study as the editor stores it in an IFC file, read back.

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
"""
import json
import re

ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(")


def entities(text):
    """(id, TYPE, argument text) of every entity of a STEP file."""
    data = text[text.find("DATA;") + 5:] if "DATA;" in text else text
    i, n = 0, len(data)
    while True:
        m = ENTITY.search(data, i)
        if not m:
            return
        j, depth = m.end(), 1
        while j < n and depth:
            c = data[j]
            if c == "'":                      # string: '' is an escaped quote
                j += 1
                while j < n and not (data[j] == "'" and data[j + 1:j + 2] != "'"):
                    j += 2 if data[j] == "'" else 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        yield int(m.group(1)), m.group(2).upper(), data[m.end():j - 1]
        i = j


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
