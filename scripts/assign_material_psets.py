"""Writes reference properties of non-masonry materials into an IFC file's
material property sets.

    python scripts/assign_material_psets.py <spec.json> <model.ifc> [<model.ifc> ...]

    python scripts/assign_material_psets.py \
        resources/survey_data/castelnuovo/non_masonry_materials.json \
        resources/ifc_examples/castelnuovo/final_example.ifc \
        resources/ifc_examples/castelnuovo/example_clean.ifc

For every material in the spec it writes, overwriting earlier values:

    Pset_MaterialCommon      MassDensity, MaterialModelType
    Pset_MaterialMechanical  YoungModulus, PoissonRatio, isStructural,
                             ConstitutiveModel
    Pset_MaterialSource      Source (where each value comes from)

These are the names core/ifc_processing/data_extractor.py reads
(MaterialModelType, isStructural); ConstitutiveModel is the name the IDS of
Chapter 5 requires, and carries the same value.

Units. data_extractor reads YoungModulus as MPa. An IFC file without a
modulus-of-elasticity unit means pascal, so the script declares N/mm2 as
that unit in the project's IfcUnitAssignment before writing: the stored
numbers are then both correct IFC and what the code expects. A file that
already declares a different modulus unit is refused rather than mixed.

Materials missing from the IFC file are reported, and the file is not
written, so a renamed material cannot silently go without properties.
"""
import json
import sys

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element

MODEL_TYPE = "ElasticIsotropic"


def modulus_unit_n_per_mm2(f):
    """Declares N/mm2 as the project's modulus-of-elasticity unit, if not already."""
    assignment = f.by_type("IfcUnitAssignment")[0]
    for u in assignment.Units:
        if getattr(u, "UnitType", None) == "MODULUSOFELASTICITYUNIT":
            dims = sorted((e.Unit.Name, e.Unit.Prefix, e.Exponent) for e in u.Elements)
            if dims == sorted([("NEWTON", None, 1), ("METRE", "MILLI", -2)]):
                return False
            raise SystemExit(f"{f}: declares another modulus unit {dims}; not mixing units")
    newton = next((u for u in assignment.Units if getattr(u, "UnitType", None) == "FORCEUNIT"), None)
    if newton is None:
        newton = f.createIfcSIUnit(None, "FORCEUNIT", None, "NEWTON")
        assignment.Units = list(assignment.Units) + [newton]
    mm = f.createIfcSIUnit(None, "LENGTHUNIT", "MILLI", "METRE")
    unit = f.createIfcDerivedUnit(
        [f.createIfcDerivedUnitElement(newton, 1), f.createIfcDerivedUnitElement(mm, -2)],
        "MODULUSOFELASTICITYUNIT", None)
    assignment.Units = list(assignment.Units) + [unit]
    return True


def write_pset(f, material, name, values):
    pset = ifcopenshell.util.element.get_pset(material, name)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.run("pset.add_pset", f, product=material, name=name)
    ifcopenshell.api.run("pset.edit_pset", f, pset=pset, properties=values)


def typed(f, ifc_type, value):
    return f.create_entity(ifc_type, value)


def apply(spec, path):
    f = ifcopenshell.open(path)
    by_name = {m.Name: m for m in f.by_type("IfcMaterial")}
    missing = sorted(set(spec) - set(by_name))
    if missing:
        raise SystemExit(f"{path}: materials not in the file: {missing}")
    added_unit = modulus_unit_n_per_mm2(f)
    for name, m in spec.items():
        mat = by_name[name]
        write_pset(f, mat, "Pset_MaterialCommon", {
            "MassDensity": typed(f, "IfcMassDensityMeasure", float(m["MassDensity"])),
            "MaterialModelType": typed(f, "IfcLabel", MODEL_TYPE),
        })
        write_pset(f, mat, "Pset_MaterialMechanical", {
            "YoungModulus": typed(f, "IfcModulusOfElasticityMeasure", float(m["YoungModulus"])),
            "PoissonRatio": typed(f, "IfcPositiveRatioMeasure", float(m["PoissonRatio"])),
            "isStructural": typed(f, "IfcBoolean", True),
            "ConstitutiveModel": typed(f, "IfcLabel", MODEL_TYPE),
        })
        write_pset(f, mat, "Pset_MaterialSource", {"Source": typed(f, "IfcText", m["source"])})
    f.write(path)
    print(f"{path}: {len(spec)} materials written"
          + (", N/mm2 declared as modulus unit" if added_unit else ""))


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    spec = json.load(open(sys.argv[1], encoding="utf-8"))["materials"]
    for path in sys.argv[2:]:
        apply(spec, path)


if __name__ == "__main__":
    main()
