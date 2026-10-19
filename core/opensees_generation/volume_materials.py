"""Materials of the volumes of a model whose STEP geometry has lost its IFC labels.

The Castelnuovo analyses mesh a prepared STEP geometry in which no solid
remembers the IFC element, nor the material, it came from.
scripts/map_castelnuovo_volume_materials.py recovers the material of every
volume from the IFC model (core.ifc_processing.ifc_step_matching) and
writes it to a JSON file; this module turns that file into one gmsh
physical group per material, and the enriched IFC model into the
:class:`Material` objects of those groups, so that each wall is analysed
with the properties derived for its own masonry type.
"""
import copy
import json

import gmsh

from core.ifc_processing.data_extractor import Material


def load(path):
    """{volume_tag: material name} from the JSON file written by
    scripts/map_castelnuovo_volume_materials.py."""
    return {int(k): v["material"] for k, v in json.load(open(path, encoding="utf-8"))["volumes"].items()}


def add_physical_groups(volume_materials, vol_tags):
    """Creates one 3D physical group per material, named after it, and
    returns {material name: [volume tags]}."""
    groups = {}
    for v in vol_tags:
        groups.setdefault(volume_materials[v], []).append(v)
    for name, vols in groups.items():
        tag = gmsh.model.addPhysicalGroup(3, vols)
        gmsh.model.setPhysicalName(3, tag, name)
    return groups


def materials_from_ifc(ifc_path, names, linear=False):
    """{name: Material} for the given material names, read from the
    property sets of the (enriched) IFC model. Masonry keeps the
    plastic-damage model written by the knowledge-graph builder unless
    ``linear`` is True; every other material, and every material when
    ``linear`` is True, is linear elastic."""
    import ifcopenshell
    db = Material.create_material_database(ifcopenshell.open(ifc_path))
    missing = [n for n in names if n not in db or not db[n].young_modulus]
    if missing:
        raise SystemExit(f"no mechanical properties in {ifc_path} for {missing}")
    out = {}
    for n in names:
        m = copy.copy(db[n])
        m.material_model_type = ("PlasticDamage" if m.material_model_type == "PlasticDamage" and not linear
                                 else "LinearElastic")
        out[n] = m
    return out


def total_weight(groups, materials, g):
    """Sum of density x g x volume over the physical groups (N, with g in m/s^2)."""
    return sum(materials[n].density * g * sum(gmsh.model.occ.getMass(3, v) for v in vols)
               for n, vols in groups.items())


def element_densities(groups, materials):
    """{gmsh element tag: density} for the 3D elements of every group, for
    computations that need the mass of each element (the OpenSees element
    tags are the gmsh ones)."""
    out = {}
    for n, vols in groups.items():
        for v in vols:
            _types, tags, _nodes = gmsh.model.mesh.getElements(3, v)
            for block in tags:
                for t in block:
                    out[int(t)] = materials[n].density
    return out


def summary(groups, materials):
    """The materials used, for the run summaries."""
    return {n: {"volumes": len(vols),
                "volume_m3": round(sum(gmsh.model.occ.getMass(3, v) for v in vols), 3),
                "model": m.material_model_type, "young_modulus_MPa": m.young_modulus,
                "poisson_ratio": m.poisson_ratio, "density_kg_m3": m.density,
                "compressive_strength_MPa": m.compressive_strength, "tensile_strength_MPa": m.tensile_strength}
            for n, vols in groups.items() for m in [materials[n]]}
