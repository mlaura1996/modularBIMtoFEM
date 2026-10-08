"""Derives HMO mechanical properties by running the ontology's own SWRL rules
with an OWL reasoner (Pellet).

This is the reasoning route. The values come from the rules defined in the
Historic Masonry Ontology, executed by a reasoner over individuals that
describe each masonry type, not from a transcription of the rules in code.
core/ifc_processing/hmo_mqi.py remains as an independent implementation of
the same rules, and cross_check() compares the two.

The rules must be the corrected ones (see resources/ontologies/README.md):
as originally published they cannot be executed, and a reasoner either
reports the ontology inconsistent or derives wrong or multiple values.

Requirements, not part of the Docker image: owlready2 0.48 and a Java
runtime. Later owlready2 releases bundle Jena libraries compiled for Java
25 and fail on older runtimes with UnsupportedClassVersionError.

How a classification becomes individuals. Each masonry type is a
MasonryWall with a RepresentativeVolumeElement, a Pattern, a Units
individual and a MasonryQualityIndex. The seven survey categories are
expressed as the named constants the score rules match on, attached to the
Pattern as dominant or sparse entities (PATTERN_ENTITIES below). Unit size
is the one parameter the rules read as a number: the classification
records a category, so the Units individual is given a representative
length range whose mean falls in that category.
"""
import os
import tempfile

HMO = "https://w3id.org/hmo#"
CASE = "https://example.org/castelnuovo#"
SAREF_HAS_VALUE = "https://saref.etsi.org/core/hasValue"

# cm; the rules classify on (min + max) / 2: small < 20, medium 20-40, large >= 40
UNIT_LENGTH_CM = {"small": (10.0, 20.0), "medium": (20.0, 40.0), "large": (40.0, 60.0)}

# Unit shape and unit material are not independent in HMO: the constant
# IrregularSoftstone triggers both a shape and a material rule, so the pair
# is mapped together. Only the combinations the case study uses are listed;
# any other raises, rather than being guessed.
SHAPE_AND_MATERIAL = {
    ("cut_or_squared", "irregular_soft_stone"): ["SquaredSoftstone"],
    ("roughly_cut_or_irregular_soft", "irregular_soft_stone"): ["RoughlyCutStone", "IrregularSoftstone"],
    ("rubble", "irregular_soft_stone"): ["RubbleStones", "IrregularSoftstone"],
}
MORTAR = {"lime": "LimeMortarJoints",
          "hydraulic_lime_or_roman_cement": "HydraulicLimeMortarJoints",
          "earth": "EarthMortarJoints"}
HORIZONTAL_JOINTS = {"not_continuous": "NotContinuousHorizontalJoints",
                     "partially_continuous": "PartiallyContinuousHorizontalJoints",
                     "continuous": "ContinuousHorizontalJoints"}
VERTICAL_JOINTS = {"aligned": "VerticallyAlignedJoints",
                   "partially_staggered": "PartiallyStaggeredJoints",
                   "properly_staggered": "ProperlyStaggeredJoints"}
# (constant, attached as dominant?) - sparse headers go through the
# hasSparsePatternEntities property, the only rule that reads it
WALL_CONNECTIONS = {"none": ("NoHeaders", True),
                    "sparse": ("HeadersBondUnits", False),
                    "frequent": ("HeadersBondUnits", True)}

PROPERTY_CLASSES = {"young_modulus_MPa": "YoungModulus",
                    "compressive_strength_MPa": "CompressiveStrength",
                    "shear_modulus_MPa": "ShearModulus",
                    "shear_strength_turnsek_cacovic_MPa": "ShearStrengthTC"}
DIRECTIONS = {"vertical": "Vertical", "out_of_plane": "OutOfPlane", "in_plane": "InPlane"}


def pattern_entities(observation):
    """Survey categories -> (dominant constants, sparse constants, unit length range)."""
    pair = (observation["unit_shape"], observation["unit_material"])
    if pair not in SHAPE_AND_MATERIAL:
        raise KeyError(f"no HMO constants defined for unit shape/material {pair}")
    dominant = list(SHAPE_AND_MATERIAL[pair])
    dominant.append(MORTAR[observation["mortar_quality"]])
    dominant.append(HORIZONTAL_JOINTS[observation["horizontal_joints"]])
    dominant.append(VERTICAL_JOINTS[observation["vertical_joints"]])
    const, is_dominant = WALL_CONNECTIONS[observation["wall_connections"]]
    sparse = []
    (dominant if is_dominant else sparse).append(const)
    return dominant, sparse, UNIT_LENGTH_CM[observation["unit_dimensions"]]


def _local(name):
    return "".join(c if c.isalnum() else "_" for c in name)


def build_individuals(classification):
    """rdflib graph of the individuals describing every type in the classification."""
    import rdflib
    from rdflib import RDF, OWL, XSD, Literal, URIRef
    h = lambda x: URIRef(HMO + x)
    c = lambda x: URIRef(CASE + x)

    g = rdflib.Graph()
    for name, t in classification["types"].items():
        k = _local(name)
        wall, rve, pat, units, mqi = (c(f"{p}_{k}") for p in ("Wall", "RVE", "Pattern", "Units", "MQI"))
        for ind, cls in ((wall, "MasonryWall"), (rve, "RepresentativeVolumeElement"), (pat, "Pattern"),
                         (units, "Units"), (mqi, "MasonryQualityIndex")):
            g.add((ind, RDF.type, OWL.NamedIndividual)); g.add((ind, RDF.type, h(cls)))
        dominant, sparse, (lo, hi) = pattern_entities(t["observation"])
        # xsd:float to match the declared range: a double would make the
        # ontology inconsistent, the two value spaces being disjoint in OWL 2
        g.add((units, h("unitsLengthHasMinimumValue"), Literal(lo, datatype=XSD.float)))
        g.add((units, h("unitsLengthMaximumValue"), Literal(hi, datatype=XSD.float)))
        g.add((wall, h("hasRepresentativeVolumeElement"), rve))
        g.add((wall, h("hasMasonryQualityIndex"), mqi))
        g.add((rve, h("hasPattern"), pat))
        g.add((pat, h("hasDominantPatternEntities"), units))
        for x in dominant:
            g.add((pat, h("hasDominantPatternEntities"), h(x)))
        for x in sparse:
            g.add((pat, h("hasSparsePatternEntities"), h(x)))
        for key, cls in PROPERTY_CLASSES.items():
            p = c(f"{cls}_{k}")
            g.add((p, RDF.type, OWL.NamedIndividual)); g.add((p, RDF.type, h(cls)))
            g.add((rve, h("hasHomogenisedMechanicalProperty"), p))
    return g


def run_pellet(kb, name="hmo_reasoner_kb"):
    """Runs Pellet over an rdflib graph and returns the reasoned owlready2 world.

    Raises RuntimeError if the graph is inconsistent, naming the file to
    pass to `pellet explain`.
    """
    import owlready2 as ow
    import rdflib
    from rdflib import OWL

    # owlready2's own N-Triples reader mis-parses files with CRLF endings,
    # so the graph is always serialised by rdflib first. owl:imports are
    # dropped: the caller passes everything to reason over, and owlready2
    # would otherwise fetch the imported ontologies from the web (HSTO
    # imports BEO and DOT), depending on which ontology it takes as the
    # one being loaded
    path = os.path.join(tempfile.gettempdir(), f"{name}.nt")
    flat = rdflib.Graph()
    for t in kb:
        if t[1] != OWL.imports:
            flat.add(t)
    flat.serialize(path, format="nt", encoding="utf-8")
    world = ow.World()
    world.get_ontology("file://" + path.replace("\\", "/")).load(format="ntriples")
    try:
        ow.sync_reasoner_pellet(world, infer_property_values=True,
                                infer_data_property_values=True, debug=0)
    except ow.OwlReadyInconsistentOntologyError as exc:
        raise RuntimeError(
            "knowledge base inconsistent; explain with: java -cp <owlready2 pellet jars> "
            f"pellet.Pellet explain --inconsistent {path}") from exc
    return world


def read_derived(world, mqi_iri, property_iris, what):
    """MQI totals and property values the reasoner derived for one wall.

    property_iris maps a PROPERTY_CLASSES key to the IRI of the individual
    carrying it. Raises RuntimeError if a quantity is missing or has more
    than one value: either means the rules or the individuals are not what
    this module assumes, and silently picking a value would hide it.
    """
    has_value = world[SAREF_HAS_VALUE]

    def one(values, label):
        values = [float(v) for v in values]
        if len(values) != 1:
            raise RuntimeError(f"{what} {label}: expected one derived value, got {values}")
        return values[0]

    mqi = world[mqi_iri]
    return {
        "mqi_total": {d: one(getattr(mqi, f"MQITotal{suffix}"), f"MQI {d}")
                      for d, suffix in DIRECTIONS.items()},
        "mechanical_properties": {key: one(has_value[world[iri]], key)
                                  for key, iri in property_iris.items()},
    }


def derive(classification, ontology_path):
    """Runs Pellet on one test wall per type and returns
    {type: {"mqi_total": {...}, "mechanical_properties": {...}}}."""
    import rdflib

    kb = rdflib.Graph()
    kb.parse(ontology_path, format="turtle")
    kb += build_individuals(classification)
    world = run_pellet(kb)
    out = {}
    for name in classification["types"]:
        k = _local(name)
        out[name] = read_derived(
            world, CASE + f"MQI_{k}",
            {key: CASE + f"{cls}_{k}" for key, cls in PROPERTY_CLASSES.items()}, name)
    return out


# Decimal places hmo_mqi.evaluate() rounds each quantity to.
ENGINE_DECIMALS = {"mqi": 3, "young_modulus_MPa": 1, "compressive_strength_MPa": 3,
                   "shear_modulus_MPa": 2, "shear_strength_turnsek_cacovic_MPa": 4}


def cross_check(derived, engine, rel_tol=1e-6):
    """Compares reasoner and engine results; returns a list of discrepancies.

    The tolerance is half a unit of the engine's rounding (see
    ENGINE_DECIMALS) plus a relative term for single precision: the rules'
    quantities have xsd:float ranges, so the reasoner computes in single
    precision while the engine uses double and then rounds.
    """
    problems = []
    for name, r in derived.items():
        e = engine[name]
        pairs = [(f"MQI {d}", "mqi", r["mqi_total"][d], e["mqi_total"][d]) for d in DIRECTIONS]
        pairs += [(key, key, r["mechanical_properties"][key], e["mechanical_properties"][key])
                  for key in PROPERTY_CLASSES]
        for what, dec_key, a, b in pairs:
            tol = 0.5 * 10 ** -ENGINE_DECIMALS[dec_key] + rel_tol * abs(b)
            if abs(a - b) > tol:
                problems.append(f"{name} {what}: reasoner {a}, engine {b}")
    return problems
