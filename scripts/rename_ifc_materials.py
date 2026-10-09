"""Renames IFC materials, so that the material names carry their meaning.

    python scripts/rename_ifc_materials.py <names.json> <in.ifc> <out.ifc>

The material name is what links an element to its mechanical properties in
the pipeline (and, for masonry, to its type in the knowledge graph), so a
model exported with authoring-tool defaults such as "Default Wall" cannot be
used as it is. names.json maps old names to new ones:

    {"names": {"Default Wall": "Double_leaf_stone_masonry", ...}}

Only the Name of the IfcMaterial entities changes; every element keeps its
material association. Names in the map that are not in the file are an
error, so a typo cannot pass silently. The input file is not modified.
"""
import json
import sys

import ifcopenshell


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    names = json.load(open(sys.argv[1], encoding="utf-8"))["names"]
    f = ifcopenshell.open(sys.argv[2])
    materials = {m.Name: m for m in f.by_type("IfcMaterial")}
    missing = sorted(set(names) - set(materials))
    if missing:
        raise SystemExit(f"materials not in {sys.argv[2]}: {missing}")
    taken = sorted(set(names.values()) & (set(materials) - set(names)))
    if taken:
        raise SystemExit(f"new names already used by other materials: {taken}")
    for old, new in names.items():
        materials[old].Name = new
        print(f"{old!r} -> {new!r}")
    f.write(sys.argv[3])
    print(f"wrote {sys.argv[3]}")


if __name__ == "__main__":
    main()
