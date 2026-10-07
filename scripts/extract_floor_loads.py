"""Extracts the floor slabs of an IFC model as a load specification.

Writes a small JSON that core.opensees_generation.floor_loads consumes, so
that the analysis scripts never need ifcopenshell and the extraction can
be re-run independently when the areal load is revised.

The horizontal structures of a masonry aggregate are frequently not
modelled as structural elements, either because the position of their
beams is not known or because their contribution has been found to be
local. Their weight still acts on the walls, and this is what lets it be
applied without representing the structure itself.

    python scripts/extract_floor_loads.py <model.ifc> <out.json> [kN/m2]

The areal load defaults to 1.5 kN/m2, a dead load representative of a
traditional timber floor with beams, boarding and finish. It is a single
figure for the whole model: where the make-up differs between units, run
the extraction per unit and merge the results.
"""
import json
import sys

import ifcopenshell
import ifcopenshell.geom
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop

DEFAULT_AREAL_LOAD_KN_M2 = 1.5


def extract(ifc_path, areal_load_kN_m2=DEFAULT_AREAL_LOAD_KN_M2):
    """Returns one record per slab with its elevation, plan extent and weight.

    The plan area is taken as volume divided by thickness rather than from
    the bounding box, which would overestimate it for any slab that is not
    rectangular. The elevation is the underside of the slab, since that is
    the level at which it bears on the walls.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_PYTHON_OPENCASCADE, True)

    model = ifcopenshell.open(ifc_path)
    records, skipped = [], []

    for slab in model.by_type("IfcSlab"):
        try:
            shape = ifcopenshell.geom.create_shape(settings, slab).geometry
        except Exception as exc:                       # noqa: BLE001
            skipped.append((slab.GlobalId, str(exc)[:80]))
            continue

        props = GProp_GProps()
        brepgprop.VolumeProperties(shape, props)
        volume = abs(props.Mass())

        box = Bnd_Box()
        brepbndlib.Add(shape, box)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        thickness = zmax - zmin
        if thickness <= 1e-6 or volume <= 1e-9:
            skipped.append((slab.GlobalId, "no usable solid"))
            continue

        area = volume / thickness
        records.append({
            "global_id": slab.GlobalId,
            "name": slab.Name,
            "predefined_type": slab.PredefinedType,
            "elevation_m": zmin,
            "thickness_m": thickness,
            "area_m2": area,
            "bbox_xy": [xmin, ymin, xmax, ymax],
            "weight_N": areal_load_kN_m2 * 1000.0 * area,
        })

    return records, skipped


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ifc_path, out_path = sys.argv[1], sys.argv[2]
    load = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_AREAL_LOAD_KN_M2

    records, skipped = extract(ifc_path, load)
    total_area = sum(r["area_m2"] for r in records)
    total_weight = sum(r["weight_N"] for r in records)

    payload = {
        "source_ifc": ifc_path,
        "areal_load_kN_m2": load,
        "slab_count": len(records),
        "total_area_m2": total_area,
        "total_weight_N": total_weight,
        "slabs": records,
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=1)

    print(f"{len(records)} slab(s), {total_area:.2f} m^2, "
          f"{total_weight/1e6:.3f} MN at {load} kN/m^2 -> {out_path}")
    for gid, why in skipped:
        print(f"  skipped {gid}: {why}")


if __name__ == "__main__":
    main()
