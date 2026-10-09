"""Exports the Castelnuovo BIM model for the knowledge graph page.

    python scripts/export_bim_for_web.py <model.ifc> --glb <page dir>/bim/model.glb
                                         --elements <bim_elements.json>

Writes
  model.glb          the geometry of every building element, one node per
                     element named by its IFC GlobalId, with its IFC class,
                     name and material names as node extras, so the page
                     can colour and identify it
  bim_elements.json  the same elements and their materials, read by the
                     knowledge graph builder (python -m core.knowledge_graph
                     build ... --bim) to link each masonry type to the IFC
                     elements made of it

The link between the BIM model and the knowledge graph is the material
name, as in the conversion to the numerical model: an element whose
material (or one of whose constituents) is the name of a masonry type of
the graph is an element of that type.

Geometry is triangulated by IfcOpenShell in world coordinates (metres),
turned from IFC's Z-up to glTF's Y-up and centred on the origin. Only
positions and indices are written: the page shades the faces flat, so
normals are not needed. Needs IfcOpenShell and numpy.
"""
import argparse
import json
import os
import struct

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue

SKIP = ("IfcOpeningElement", "IfcSpace", "IfcVirtualElement")


def material_names(element):
    names = []
    for m in ue.get_materials(element):
        if m is not None and getattr(m, "Name", None) and m.Name not in names:
            names.append(m.Name)
    return names


def write_glb(path, meshes):
    """meshes: list of (name, extras, positions float32 (n,3), indices uint32 (m,))."""
    buf = bytearray()
    views, accessors, gl_meshes, nodes = [], [], [], []

    def add_view(data, target):
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), "target": target})
        buf.extend(data)
        return len(views) - 1

    for name, extras, pos, idx in meshes:
        pv = add_view(pos.astype("<f4").tobytes(), 34962)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()})
        iv = add_view(idx.astype("<u4").tobytes(), 34963)
        accessors.append({"bufferView": iv, "componentType": 5125, "count": len(idx), "type": "SCALAR"})
        gl_meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": len(accessors) - 2},
                                                        "indices": len(accessors) - 1}]})
        nodes.append({"name": name, "mesh": len(gl_meshes) - 1, "extras": extras})
    while len(buf) % 4:
        buf.append(0)
    gltf = {"asset": {"version": "2.0", "generator": "openBIMtoFEM export_bim_for_web.py"},
            "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes,
            "meshes": gl_meshes, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(buf), 0x004E4942)); f.write(bytes(buf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc")
    ap.add_argument("--glb", required=True)
    ap.add_argument("--elements", required=True)
    a = ap.parse_args()
    IFC, GLB, ELEMENTS_JSON = a.ifc, a.glb, a.elements
    f = ifcopenshell.open(IFC)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    elements = [e for e in f.by_type("IfcElement") if not e.is_a() in SKIP]
    it = ifcopenshell.geom.iterator(settings, f, include=elements)
    raw = []
    if it.initialize():
        while True:
            shape = it.get()
            el = f.by_id(shape.id)
            v = np.array(shape.geometry.verts, dtype=np.float64).reshape(-1, 3)
            t = np.array(shape.geometry.faces, dtype=np.uint32)
            if len(t):
                raw.append((el, v, t))
            if not it.next():
                break

    lo = np.min([v.min(axis=0) for _, v, _ in raw], axis=0)
    hi = np.max([v.max(axis=0) for _, v, _ in raw], axis=0)
    centre = (lo + hi) / 2
    centre[2] = lo[2]            # ground at y = 0

    meshes, records = [], []
    for el, v, t in raw:
        rec = {"global_id": el.GlobalId, "ifc_class": el.is_a(), "name": el.Name or "",
               "materials": material_names(el)}
        records.append(rec)
        p = v - centre
        yup = np.column_stack([p[:, 0], p[:, 2], -p[:, 1]])          # Z-up -> Y-up
        meshes.append((el.GlobalId, rec, yup.astype(np.float32), t))

    os.makedirs(os.path.dirname(GLB), exist_ok=True)
    write_glb(GLB, meshes)
    meta = {"_meta": {"source": IFC.replace("\\", "/"),
                      "description": "Building elements of the BIM model and their materials, exported by "
                                     "scripts/export_bim_for_web.py. A material that is the name of a masonry "
                                     "type links the element to that type in the knowledge graph."},
            "elements": sorted(records, key=lambda r: (r["ifc_class"], r["name"], r["global_id"]))}
    with open(ELEMENTS_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    counts = {}
    for r in records:
        for m in r["materials"] or ["(none)"]:
            counts[m] = counts.get(m, 0) + 1
    print(f"{len(records)} elements, {sum(len(t) for *_, t in meshes) // 3} triangles, "
          f"{os.path.getsize(GLB) / 1e6:.1f} MB -> {GLB}")
    print("elements per material:", dict(sorted(counts.items())))
    print("model size (m):", np.round(hi - lo, 2).tolist())


if __name__ == "__main__":
    main()
