"""Applies the weight and mass of unmodelled horizontal structures.

When the floors and roofs of an aggregate are not represented as
structural elements, their geometry leaves the model but their weight
does not leave the building. This module puts that weight back on the
walls, as gravity load during the static stage and as translational mass
for the dynamic one, without representing the structure itself.

It consumes the JSON written by scripts/extract_floor_loads.py, so the
analysis scripts do not need ifcopenshell.

NOT EXERCISED BY THE CASTELNUOVO ANALYSES REPORTED IN THE THESIS. Those
runs carry the masonry self-weight only, and the floors contribute
neither geometry nor load to them. This module exists so that the
horizontal structures can be included in later applications, which is
where the distinction between an omitted element and an omitted load
starts to matter.

Order of use, matching docker/opensees/timehistory_castelnuovo.py:

    levels = load_floor_loads("output/castelnuovo/floor_loads.json")

    ops.timeSeries("Linear", 10)
    ops.pattern("Plain", 10, 10)
    applied = apply_floor_loads(levels, node_z, coord_by_tag,
                                candidate_nodes=all_node_tags)
    # ... static gravity analysis, then ops.loadConst("-time", 0.0)

`apply_floor_loads` must be called inside an active Plain pattern and
before the gravity analysis, so that its load is held constant by the
same loadConst that fixes the self-weight. The mass it assigns is
independent of the pattern and is added to the element mass already
derived from the material density.
"""
import json

import openseespy.opensees as ops

G_ACCEL = 9.81


def load_floor_loads(path):
    """Reads the JSON written by scripts/extract_floor_loads.py."""
    with open(path) as fh:
        return json.load(fh)


def _supporting_nodes(slab, node_z, coord_by_tag, candidate_nodes, z_tol):
    """Nodes that lie at the slab's bearing level and within its plan extent.

    The bounding box is used rather than the true outline because the
    outline is not carried in the load specification. A slab whose plan
    is strongly non-convex will therefore recruit nodes that do not in
    fact support it, which is acceptable while the whole purpose is to
    place a weight on the walls of the right storey, and is not once the
    distribution itself matters.
    """
    xmin, ymin, xmax, ymax = slab["bbox_xy"]
    z0 = slab["elevation_m"]
    found = []
    for tag in candidate_nodes:
        if abs(node_z[tag] - z0) > z_tol:
            continue
        x, y, _z = coord_by_tag[tag]
        if xmin <= x <= xmax and ymin <= y <= ymax:
            found.append(tag)
    return found


def apply_floor_loads(levels, node_z, coord_by_tag, candidate_nodes,
                      z_tol=0.15, as_load=True, as_mass=True,
                      vertical_dof=3, g=G_ACCEL):
    """Distributes each slab's weight over the nodes that carry it.

    The weight is shared equally between the supporting nodes. This is
    coarser than a tributary-area distribution and is adopted because the
    quantity that matters for the global response is the total mass and
    the storey at which it acts, not its distribution along a wall.

    Loads and masses are accumulated per node before being issued,
    because `ops.mass` replaces the mass of a node rather than adding to
    it, so a node supporting two slabs would otherwise keep only the
    second.

    Returns {"nodes": n, "weight_N": w, "unsupported": [...]}, the last
    listing any slab for which no node was found, which means the level
    tolerance or the plan extent did not match the mesh.
    """
    load_per_node, mass_per_node = {}, {}
    unsupported = []
    total_weight = 0.0

    for slab in levels["slabs"]:
        nodes = _supporting_nodes(slab, node_z, coord_by_tag,
                                  candidate_nodes, z_tol)
        if not nodes:
            unsupported.append(slab["global_id"])
            continue

        share = slab["weight_N"] / len(nodes)
        total_weight += slab["weight_N"]
        for tag in nodes:
            load_per_node[tag] = load_per_node.get(tag, 0.0) + share
            mass_per_node[tag] = mass_per_node.get(tag, 0.0) + share / g

    if as_load:
        for tag, w in load_per_node.items():
            vec = [0.0, 0.0, 0.0]
            vec[vertical_dof - 1] = -w          # downward
            ops.load(int(tag), *vec)

    if as_mass:
        for tag, m in mass_per_node.items():
            ops.mass(int(tag), m, m, m)

    return {
        "nodes": len(load_per_node),
        "weight_N": total_weight,
        "unsupported": unsupported,
    }
