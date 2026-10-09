"""Material database of masonry types characterised with the HMO/MQI rules.

Shared by every case study: compute_all() runs the Python implementation of
the rules (core/ifc_processing/hmo_mqi.py) on a masonry classification, and
write_material_database() writes the result in the field shape of
core.ifc_processing.data_extractor.Material, so that
utils.dict_helper.load_material_objects can read it. The knowledge graph
builder (core/knowledge_graph) uses the same functions to write the
database from the values the reasoner derives.
"""
import json

from core.ifc_processing.hmo_mqi import MasonryObservation, evaluate


def compute_all(classification):
    results = {}
    for name, t in classification["types"].items():
        obs = MasonryObservation(**t["observation"])
        r = evaluate(obs, mass_density_kg_m3=t["mass_density_kg_m3"])
        r["description"] = t["description"]
        r["evidence"] = t["evidence"]
        r["flags"] = t["flags"]
        r["ntc_comparison"] = t.get("ntc_comparison")
        results[name] = r
    return results


def print_summary(results):
    """Prints fm/E/G/tau0 for eyeball comparison against the prose numbers
    in masonry_classification.json's ntc_comparison notes (computed by hand
    during the chat session before this script existed) - the notes are
    free text, not parsed here, so this is a manual cross-check, not an
    automated one.
    """
    for name, r in results.items():
        mech = r["mechanical_properties"]
        print(f"{name}: fm={mech['compressive_strength_MPa']} E={mech['young_modulus_MPa']} "
              f"G={mech['shear_modulus_MPa']} tau0={mech['shear_strength_turnsek_cacovic_MPa']}")


# ft/fc ratio, not derived from HMO (which has no tensile-strength rule at
# all - see write_material_database's docstring) but from PROJECT_BRIEF.md's
# own Chapter 6 (SERA-AIMS) reference masonry: ft=0.17 MPa at fc=1.30 MPa,
# i.e. ft/fc = 0.1308. Chosen over leaving tensile_strength at 0 because 0
# is not inert downstream: traced core.opensees_generation.model_builder
# .create_plastic_damage_elements -> models.damage_law.ConstitutiveLaws
# .ExponentialSoftening_Tension.tension(E, ft=0, Gt, side_length) and ran it
# (see chat log) - with ft=0 the loop's own convergence check
# (`if stress > s0*0.05`) is `0 > 0`, False on the first iteration, so the
# function returns a degenerate two-point curve Te=[0,0.0], Ts=[0,0],
# Td=[0,0] instead of an actual softening branch. That gets passed straight
# into `nDMaterial('ASDConcrete3D', ..., '-Te', 0, 0.0, ...)` - "not
# derived by HMO" silently becomes "asserted zero tensile strength" with no
# distinction between the two. A nonzero, sourced estimate avoids that.
TENSILE_TO_COMPRESSIVE_RATIO = 0.17 / 1.30


def write_material_database(results, path):
    """Field-compatible with core.ifc_processing.data_extractor.Material:
    name, density, young_modulus, poisson_ratio, is_structural,
    material_model_type, compressive_strength, tensile_strength,
    compression_fracture_energy, tensile_fracture_energy,
    compressive_elastic_behaviour.

    HMO derives compressive strength but not tensile strength (no SWRL rule
    for it at all, checked - not merely a gap in this script). tensile_strength
    here is compressive_strength * TENSILE_TO_COMPRESSIVE_RATIO (see that
    constant's comment for why 0 was rejected, not just "improved").
    compression/tensile_fracture_energy are left at 0, which - unlike
    tensile_strength - is not a placeholder without consequence either way:
    create_plastic_damage_elements already falls back to
    Gc = 15 + 0.43*fc - 0.0036*fc^2 and Gt = 0.025*(fc/10)^0.7 (Bazant,
    cited there) when the material's own values are 0, so leaving them at 0
    activates an existing, deliberate fallback rather than leaving a gap.

    Shear strength (Turnsek-Cacovic, computed by hmo_mqi.py) is NOT a
    Material field - core.ifc_processing.data_extractor.Material has no
    such attribute, and create_plastic_damage_elements has no shear-strength
    parameter to receive it (ASDConcrete3D's shear behaviour emerges from
    the triaxial damage-plasticity formulation itself, not from an explicit
    input). Kept in the JSON under the "_shear_strength_turnsek_cacovic_MPa"
    key for traceability, but load_material_objects (utils/dict_helper.py)
    deliberately excludes every "_"-prefixed key from the Material() call,
    so it is inert as far as element creation goes - documentation, not a
    live input.
    """
    db = {}
    for name, r in results.items():
        mech = r["mechanical_properties"]
        fc = mech["compressive_strength_MPa"]
        db[name] = {
            "name": name,
            "density": mech["mass_density_kg_m3"],
            "young_modulus": mech["young_modulus_MPa"],
            "poisson_ratio": 0.2,  # literature default for masonry, not MQI-derived - HMO has no rule for it
            "is_structural": True,
            "material_model_type": "PlasticDamage",
            "compressive_strength": fc,
            "tensile_strength": round(fc * TENSILE_TO_COMPRESSIVE_RATIO, 3),
            "compression_fracture_energy": 0,
            "tensile_fracture_energy": 0,
            "compressive_elastic_behaviour": 0,
            "_mqi_total": r["mqi_total"],
            "_shear_modulus_MPa": mech["shear_modulus_MPa"],
            "_shear_strength_turnsek_cacovic_MPa": mech["shear_strength_turnsek_cacovic_MPa"],
            "_evidence": r["evidence"],
            "_flags": r["flags"],
            "_derivation": r.get("derivation", ENGINE_DERIVATION),
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)


ENGINE_DERIVATION = "core/ifc_processing/hmo_mqi.py (Python implementation of the HMO rules)"
