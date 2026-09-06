def filter_materials_by_name(materials_dict, selected_names):
    """
    Filters a materials dictionary to include only the materials whose names are in the selected_names list.

    Parameters:
        materials_dict (dict): A dictionary of Material objects (keys are material names).
        selected_names (list): A list of material names to keep.

    Returns:
        dict: A filtered dictionary containing only the selected materials.
    """
    return {name: material for name, material in materials_dict.items() if name in selected_names}


def load_material_objects(json_path):
    """
    Builds a {name: Material} dict from a JSON material database - the
    counterpart to core.ifc_processing.data_extractor.Material.create_material_database,
    which builds the same shape from IFC psets instead. Was already imported
    by in_plane_wall.py / out_of_plane_test.py (`from utils.dict_helper
    import load_material_objects`) but had never actually been implemented -
    those two scripts have been unable to run without it. See
    docker/opensees/castelnuovo_hmo_graph.py for a generator that produces
    a compatible JSON file (output/castelnuovo/material_database.json) from
    survey-derived (HMO/MQI) properties rather than from an IFC file.

    Expects one JSON object per material, keyed by material name, with the
    same field names as Material.__init__ (name, density, young_modulus,
    poisson_ratio, is_structural, material_model_type, compressive_strength,
    tensile_strength, compression_fracture_energy, tensile_fracture_energy,
    compressive_elastic_behaviour). Extra keys (e.g. castelnuovo_hmo_graph.py
    writes "_evidence", "_flags", "_mqi_total" alongside the Material fields
    for traceability) are ignored - only known fields are passed to Material().
    Any Material field that is JSON `null` (e.g. tensile_strength when the
    source data has no way to derive it) is coerced to 0, matching how the
    rest of this codebase already treats an absent/unknown value (see
    Material.assign_material_tags: `info.get('thickness', 0) or 0`) rather
    than passing None into element/material creation downstream.
    """
    import json
    from core.ifc_processing.data_extractor import Material

    # Passed through as-is: a null/false value here is meaningful, not "unknown".
    passthrough_fields = ("name", "is_structural", "material_model_type")
    # Coerced null -> 0: matches how the rest of this codebase already
    # treats an absent numeric property (see Material.assign_material_tags).
    numeric_fields = (
        "density", "young_modulus", "poisson_ratio", "compressive_strength",
        "tensile_strength", "compression_fracture_energy",
        "tensile_fracture_energy", "compressive_elastic_behaviour",
    )

    with open(json_path) as f:
        raw = json.load(f)

    materials = {}
    for name, fields in raw.items():
        kwargs = {k: fields.get(k) for k in passthrough_fields}
        kwargs.update({k: fields.get(k) or 0 for k in numeric_fields})
        materials[name] = Material(**kwargs)
    return materials