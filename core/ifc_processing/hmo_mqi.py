"""
Masonry Quality Index (MQI) engine for the Historic Masonry Ontology (HMO).

Reusable, generic implementation of the scoring tables, the three
directional MQI totals, and the four SWRL-derived mechanical-property
formulas defined in HMO (https://w3id.org/hmo, published ontology at
github.com/mlaura1996/HistoricMasonryOntology). Every table and formula
here was transcribed directly from the SWRL rule bodies in ontology.ttl
(not from the thesis prose, which only works one example end to end, and
not from the published documentation page, which lists rule names but not
their thresholds) - so this module IS the machine-readable form of those
rules, kept in sync with the ontology by construction.

Two things this module deliberately does NOT do:
  - It does not classify a wall from photos or measurements itself. That
    judgement (which score each of the 7 parameters gets, for a given
    masonry) belongs to the survey/case-study layer - see
    resources/survey_data/ for worked classifications and how they cite
    their photographic/documentary evidence.
  - It does not implement a Mohr-Coulomb shear-strength rule. HMO defines
    the class (hmo:ShearStrengthMohrCoulomb) but, as of the ontology
    version this was read from, has no SWRL rule deriving it - only the
    Turnsek-Cacovic criterion is implemented. mechanical_properties()
    returns None for it rather than inventing a formula.

Units: the formula coefficients (279.82, 0.1298, 1.6841, 814.06, ...) are
the ontology's own literals, unconverted. They reproduce Borri's published
correlations, which are in MPa for stresses and moduli - that is the unit
system these outputs are in, regardless of what unit system the rest of a
given model uses. Convert explicitly at the call site (see
core/opensees_generation/tcl_export.py's Kn/Kt unit-conversion comment for
why this matters - a masonry material with mismatched units is a much
harder bug to notice than one with sound units, because everything still
"runs", it just runs on the wrong physics).
"""

from dataclasses import dataclass, field, asdict

DIRECTIONS = ("vertical", "out_of_plane", "in_plane")  # tuple index 0,1,2 throughout


# ---------------------------------------------------------------------
# MQI parameter score tables, (score_vertical, score_out_of_plane, score_in_plane)
# per category. Transcribed verbatim from the SWRL rule bodies in
# ontology.ttl - see the module docstring. Every named category below
# corresponds 1:1 to an SWRL rule label in the ontology (e.g. "cut_or_squared"
# aggregates MQI_SS_BarelyCutStone / MQI_SS_Bricks / MQI_SS_HollowBricks /
# MQI_SS_SquaredHardStone / MQI_SS_SquaredSoftStone, which all score
# identically at (3, 2, 2)).
# ---------------------------------------------------------------------

UNIT_DIMENSIONS = {
    # avg(min, max) unit length in cm
    "small": (0, 0, 0),          # < 20 cm
    "medium": (0.5, 0.5, 0.5),   # 20-40 cm
    "large": (1, 1, 1),          # >= 40 cm
}

UNIT_SHAPE = {
    "rubble": (0, 0, 0),
    "roughly_cut_or_irregular_soft": (1.5, 1, 1),
    "cut_or_squared": (3, 2, 2),
}

UNIT_MATERIAL = {
    "bricks": (1, 1, 1),
    "hollow_bricks_lt30pct": (0.3, 0.5, 0.3),
    "hollow_bricks_30_55pct": (0.7, 0.7, 0.7),
    "hollow_bricks_gt55pct": (1, 1, 1),
    "damaged": (0.3, 0.5, 0.3),
    "irregular_soft_stone": (0.7, 0.7, 0.7),
    "squared_hard_stone": (1, 1, 1),
}

MORTAR_QUALITY = {
    "earth": (0, 0, 0),
    "lime": (0.5, 1, 0.5),
    "hydraulic_lime_or_roman_cement": (2, 1, 1),
    "dry_joints": (0, 0, 0),
}

HORIZONTAL_JOINTS = {
    "not_continuous": (0, 0, 0),
    "partially_continuous": (1, 1, 0.5),
    "continuous": (2, 1, 2),
}

VERTICAL_JOINTS = {
    "aligned": (0, 0, 0),
    "partially_staggered": (0.5, 1, 0.5),
    "properly_staggered": (1, 1, 2),
}

WALL_CONNECTIONS = {  # diatoni / header frequency between leaves
    "none": (0, 0, 0),
    "sparse": (1, 1.5, 1),
    "frequent": (1, 3, 2),
}


@dataclass
class MasonryObservation:
    """The 7 MQI parameters for one masonry type, as category keys into the
    score tables above (not raw numbers - keeps a classification
    self-documenting: `unit_shape="cut_or_squared"` is legible in a way
    `(3, 2, 2)` is not).
    """
    unit_dimensions: str
    unit_shape: str
    unit_material: str
    mortar_quality: str
    horizontal_joints: str
    vertical_joints: str
    wall_connections: str

    def scores(self):
        return {
            "unit_dimensions": UNIT_DIMENSIONS[self.unit_dimensions],
            "unit_shape": UNIT_SHAPE[self.unit_shape],
            "unit_material": UNIT_MATERIAL[self.unit_material],
            "mortar_quality": MORTAR_QUALITY[self.mortar_quality],
            "horizontal_joints": HORIZONTAL_JOINTS[self.horizontal_joints],
            "vertical_joints": VERTICAL_JOINTS[self.vertical_joints],
            "wall_connections": WALL_CONNECTIONS[self.wall_connections],
        }


def mqi_total(obs: MasonryObservation) -> dict:
    """MQITotal_dir = (HorizJoints + VertJoints + Mortar + Shape + WallConn
    + Dimensions)_dir * UnitMaterial_dir, evaluated per direction.

    Verified against the MQI_InPlane SWRL rule body (ontology.ttl, rule
    label "MQI_InPlane"): swrlb:add sums six of the seven parameters, then
    swrlb:multiply scales by the seventh (unit material/properties) - the
    material-quality score is a multiplier, not an addend, unlike the
    other six. Same structure for MQI_OutOfPlane and MQI_Vertical.
    """
    s = obs.scores()
    totals = {}
    for i, d in enumerate(DIRECTIONS):
        additive = (s["horizontal_joints"][i] + s["vertical_joints"][i]
                    + s["mortar_quality"][i] + s["unit_shape"][i]
                    + s["wall_connections"][i] + s["unit_dimensions"][i])
        totals[d] = additive * s["unit_material"][i]
    return totals


def mechanical_properties(mqi: dict) -> dict:
    """Homogenised mechanical properties from the MQI totals, via the four
    SWRL rules HMO implements (ShearModulusMQI, ShearStrengthMQI [Turnsek-
    Cacovic], CompressiveStrenghMQI, YoungModulusMQI - exact rule labels,
    including the ontology's own typo in "Strengh"). G and shear strength
    use MQITotalInPlane; compressive strength and Young's modulus use
    MQITotalVertical - this in-plane/vertical split is in the ontology
    itself, not a simplification introduced here.

    No mass-density rule exists in HMO (density is a material physical
    constant, not derived from a workmanship-quality index) and no
    Mohr-Coulomb shear-strength rule exists either (see module docstring)
    - both keys are present for schema stability but density must be
    supplied from elsewhere and shear_strength_mohr_coulomb_MPa is always
    None.
    """
    mqi_ip = mqi["in_plane"]
    mqi_v = mqi["vertical"]
    shear_modulus = 279.82 * (2.72 ** (0.1298 * mqi_ip))
    shear_strength_tc = 0.0192 + 0.0005 * (mqi_ip ** 2) + 0.0074 * mqi_ip
    compressive_strength = 1.6841 * (2.72 ** (0.1572 * mqi_v))
    young_modulus = 814.06 * (2.72 ** (0.1381 * mqi_v))
    return {
        "shear_modulus_MPa": round(shear_modulus, 2),
        "shear_strength_turnsek_cacovic_MPa": round(shear_strength_tc, 4),
        "compressive_strength_MPa": round(compressive_strength, 3),
        "young_modulus_MPa": round(young_modulus, 1),
        "shear_strength_mohr_coulomb_MPa": None,
        "mass_density_kg_m3": None,
    }


def evaluate(obs: MasonryObservation, mass_density_kg_m3: float = None) -> dict:
    """Convenience wrapper: MasonryObservation -> full MQI + mechanical
    property report. mass_density_kg_m3 is passed through as-is (HMO has
    no rule for it - supply it from material identification, e.g. a
    literature value for the specific stone/brick type) and merged into
    the mechanical_properties dict so callers get one flat result.
    """
    mqi = mqi_total(obs)
    mech = mechanical_properties(mqi)
    if mass_density_kg_m3 is not None:
        mech["mass_density_kg_m3"] = mass_density_kg_m3
    return {
        "scores": obs.scores(),
        "mqi_total": {k: round(v, 3) for k, v in mqi.items()},
        "mechanical_properties": mech,
    }
