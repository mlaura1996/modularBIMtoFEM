"""Builds the Castelnuovo di Porto knowledge graph from the three ontologies
and derives the masonry properties in it with a reasoner.

    python docker/opensees/castelnuovo_knowledge_graph.py

One graph, populated from two data files and checked by Pellet:

  resources/survey_data/castelnuovo/survey_record.json
      who did what, which documents exist, which facade each photo shows
  resources/survey_data/castelnuovo/masonry_classification.json
      the seven MQI parameters of each masonry type, with their evidence

  HSV   historic centre > aggregate > structural units; facades; the
        documents (photos, point clouds, drawings, BIM model, publications)
        with the people who acquired, processed or authored them
  HSTO  facades as structural parts, each made of a masonry wall; the
        timber floors of each unit; the arched opening of facade 419
  HMO   the wall of each facade, an hmo:MasonryWall (the range HSTO gives
        isMadeOf), with its representative volume element, pattern,
        quality index and the properties the rules derive; one wall per
        facade, each carrying the classification of its masonry type

Pellet runs over the three ontologies (resources/ontologies/) and these
individuals together, so the whole graph is checked for consistency, and
the quality indices and properties it derives are written back into the
graph. They are checked against core/ifc_processing/hmo_mqi.py, and the
material database the analyses read is written from them.

Writes output/castelnuovo/knowledge_graph.ttl and
output/castelnuovo/material_database.json. Needs Java and owlready2 0.48
(see resources/ontologies/README.md).

Where the ontologies have no term for something the record holds, a
standard vocabulary is used instead of misusing a term with the wrong
domain: PROV-O for activities and derivation, Dublin Core for dates,
identifiers and part-whole decomposition, FOAF for people and
organisations, SKOS for the masonry types. In particular HSV's contains
stops at the structural unit (its domain is aggregate, centre or region),
and neither HSV nor HSTO relates a unit to its facades or floors, so that
decomposition is recorded with dcterms:hasPart. Connections between units
(hsto:Quoin, hsto:Tie) are not asserted: the survey documents quoined
corners in the aggregate generally, not which pair of facades they join.
"""
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rdflib
from rdflib import RDF, RDFS, OWL, XSD, Literal, Namespace, URIRef
from rdflib.collection import Collection

from core.ifc_processing.hmo_reasoner import (
    PROPERTY_CLASSES, ENGINE_DECIMALS, cross_check, pattern_entities, read_derived, run_pellet)
import castelnuovo_material_engine as engine_route

SURVEY_PATH = "resources/survey_data/castelnuovo/survey_record.json"
CLASSIFICATION_PATH = "resources/survey_data/castelnuovo/masonry_classification.json"
ONTOLOGIES = {"hmo": "resources/ontologies/hmo.ttl",
              "hsv": "resources/ontologies/hsv.ttl",
              "hsto": "resources/ontologies/hsto.ttl"}
OUT_DIR = "output/castelnuovo"

C = Namespace("https://example.org/castelnuovo#")
HSV = Namespace("https://w3id.org/hsv#")
HSTO = Namespace("https://w3id.org/hsto#")
HMO = Namespace("https://w3id.org/hmo#")
SAREF = Namespace("https://saref.etsi.org/core/")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

DIRECTION_PROPS = {"vertical": "MQITotalVertical", "out_of_plane": "MQITotalOutOfPlane",
                   "in_plane": "MQITotalInPlane"}
UNITS = ("417", "418", "419", "420")


def ind(g, iri, *classes, label=None):
    g.add((iri, RDF.type, OWL.NamedIndividual))
    for c in classes:
        g.add((iri, RDF.type, c))
    if label:
        g.add((iri, RDFS.label, Literal(label, lang="en")))
    return iri


def build(survey, classification):
    g = rdflib.Graph()
    for p, ns in (("", C), ("hsv", HSV), ("hsto", HSTO), ("hmo", HMO), ("saref", SAREF),
                  ("prov", PROV), ("dcterms", DCT), ("foaf", FOAF), ("skos", SKOS)):
        g.bind(p, ns)

    # --- people, organisations, activities (FOAF, PROV-O) -----------------
    for oid, name in survey["organisations"].items():
        ind(g, C[oid], FOAF.Organization)
        g.add((C[oid], FOAF.name, Literal(name)))
    for pid, p in survey["people"].items():
        ind(g, C[pid], FOAF.Person)
        g.add((C[pid], FOAF.name, Literal(p["name"])))
        g.add((C[p["affiliation"]], FOAF.member, C[pid]))
    for aid, a in survey["activities"].items():
        ind(g, C[aid], PROV.Activity, label=a["label"])
        for pid in a["people"]:
            g.add((C[aid], PROV.wasAssociatedWith, C[pid]))
        # roles HSV has no class for (supervision, research) are PROV roles,
        # carried by a qualified association between the activity and the person
        for pid, role in a.get("roles", {}).items():
            role_iri = C["Role_" + "".join(w.capitalize() for w in role.split())]
            ind(g, role_iri, PROV.Role, label=role)
            assoc = ind(g, C[f"{aid}_{pid}_Association"], PROV.Association)
            g.add((C[aid], PROV.qualifiedAssociation, assoc))
            g.add((assoc, PROV.agent, C[pid]))
            g.add((assoc, PROV.hadRole, role_iri))
        if "date" in a:
            g.add((C[aid], DCT.date, Literal(a["date"], datatype=XSD.date)))
        if "start" in a:
            g.add((C[aid], PROV.startedAtTime, Literal(a["start"], datatype=XSD.dateTime)))
            g.add((C[aid], PROV.endedAtTime, Literal(a["end"], datatype=XSD.dateTime)))
        if "instrument" in a:
            g.add((C[aid], RDFS.comment, Literal(f"Instrument: {a['instrument']}", lang="en")))

    # --- the built context (HSV) ------------------------------------------
    centre = ind(g, C.CastelnuovoDiPorto, HSV.HistoricCentre, label="Historic centre of Castelnuovo di Porto")
    aggregate = ind(g, C.Aggregate, HSV.Aggregate,
                    label="Aggregate between Piazza Garibaldi and Via Umberto I")
    technique = ind(g, C.MuraturaATufelli, HSV.TraditionalConstructionTechnique,
                    label="Muratura a tufelli")
    g.add((centre, HSV.contains, aggregate))
    g.add((centre, HSV.hasTraditionalConstructionTechnique, technique))

    # --- documents other than photos (HSV, PROV-O) --------------------------
    for did, d in survey["documents"].items():
        doc = ind(g, C[did], HSV[d["class"]], label=d["label"])
        for pid in d.get("authors", []):
            g.add((C[pid], RDF.type, HSV.Author)); g.add((doc, HSV.hasAuthor, C[pid]))
        for pid in d.get("acquired_by", []):
            g.add((C[pid], RDF.type, HSV.Inspector)); g.add((doc, HSV.acquiredBy, C[pid]))
        for pid in d.get("post_processed_by", []):
            g.add((C[pid], RDF.type, HSV.PostProcesser)); g.add((doc, HSV.postProcessedBy, C[pid]))
        if "activity" in d:
            g.add((doc, PROV.wasGeneratedBy, C[d["activity"]]))
        if "used_by" in d:
            g.add((C[d["used_by"]], PROV.used, doc))
        if "derived_from" in d:
            g.add((doc, PROV.wasDerivedFrom, C[d["derived_from"]]))
        if "created" in d:
            g.add((doc, DCT.created, Literal(d["created"], datatype=XSD.date)))
        if d["class"] != "Publication":
            g.add((aggregate, HSV.hasDocument, doc))

    # --- structural units and their floors (HSV, HSTO) ------------------------
    for u in UNITS:
        unit = ind(g, C[f"Unit_{u}"], HSV.StructuralUnit, label=f"Structural unit {u} (cadastral identifier)")
        g.add((aggregate, HSV.contains, unit))
        floor = ind(g, C[f"Floor_{u}"], HSTO.TimberFloor, label=f"Timber floors of unit {u}")
        g.add((floor, HSTO.hasAccessibility, Literal(False)))
        g.add((floor, RDFS.comment, Literal(
            "Generic: timber floors alla romana documented for the aggregate as a whole; "
            "the interiors of the case-study units could not be inspected.", lang="en")))
        g.add((unit, DCT.hasPart, floor))

    # --- masonry types (SKOS) -----------------------------------------------
    for name, t in classification["types"].items():
        mt = ind(g, C[name], SKOS.Concept, label=name)
        g.add((mt, SKOS.definition, Literal(t["description"], lang="en")))
        for flag in t["flags"]:
            g.add((mt, RDFS.comment, Literal(flag, lang="en")))

    # --- facades, their photos and their walls (HSV, HSTO, HMO) -------------
    walls = {}
    photo_people = survey["activities"]["PhotographicCampaign"]["people"]
    for pid in photo_people:
        g.add((C[pid], RDF.type, HSV.Inspector))
    for fid, f in survey["facades"].items():
        k = fid.replace("Facade_", "")
        facade = ind(g, C[fid], HSV.Facade, HSTO.Facade, label=f"Facade {k} of unit {f['unit']}")
        g.add((C[f"Unit_{f['unit']}"], DCT.hasPart, facade))
        g.add((facade, HSTO.isBuiltWithTraditionalConstructionTechnique, technique))
        photos = []
        for i, ph in enumerate(f["photos"], 1):
            photo = ind(g, C[f"Photo_{k}_{i:02d}"], HSV.Photo)
            g.add((photo, DCT.identifier, Literal(ph["file"])))
            if ph["taken"]:
                g.add((photo, DCT.created, Literal(ph["taken"], datatype=XSD.dateTime)))
            for pid in photo_people:
                g.add((photo, HSV.acquiredBy, C[pid]))
            g.add((photo, PROV.wasGeneratedBy, C.PhotographicCampaign))
            g.add((facade, HSV.hasDocument, photo))
            g.add((photo, HSV.isDocumentOf, facade))
            photos.append(photo)

        wall = ind(g, C[f"Wall_{k}"], HMO.MasonryWall, label=f"Masonry wall of facade {k}")
        g.add((facade, HSTO.isMadeOf, wall))
        g.add((wall, DCT.type, C[f["masonry_type"]]))
        walls[k] = (wall, f["masonry_type"], photos)

    opening = ind(g, C.Opening_419, HSTO.HistoricOpening,
                  label="Opening with an arch of dressed tuff voussoirs, facade 419")
    g.add((C.Facade_419, HSTO.hasHistoricOpening, opening))

    # --- HMO characterisation of each wall ------------------------------------
    prop_iris = {}
    for k, (wall, mtype, photos) in walls.items():
        t = classification["types"][mtype]
        rve = ind(g, C[f"RVE_{k}"], HMO.RepresentativeVolumeElement)
        pattern = ind(g, C[f"Pattern_{k}"], HMO.Pattern)
        units = ind(g, C[f"Units_{k}"], HMO.Units)
        mqi = ind(g, C[f"MQI_{k}"], HMO.MasonryQualityIndex)
        g.add((wall, HMO.hasRepresentativeVolumeElement, rve))
        g.add((wall, HMO.hasMasonryQualityIndex, mqi))
        g.add((rve, HMO.hasPattern, pattern))
        dominant, sparse, (lo, hi) = pattern_entities(t["observation"])
        # xsd:float as the range declares: a double would be inconsistent
        g.add((units, HMO.unitsLengthHasMinimumValue, Literal(lo, datatype=XSD.float)))
        g.add((units, HMO.unitsLengthMaximumValue, Literal(hi, datatype=XSD.float)))
        g.add((units, RDFS.comment, Literal(
            f"Representative length range for the '{t['observation']['unit_dimensions']}' category "
            "recorded by the survey, not measured unit lengths.", lang="en")))
        g.add((pattern, HMO.hasDominantPatternEntities, units))
        for x in dominant:
            g.add((pattern, HMO.hasDominantPatternEntities, HMO[x]))
        for x in sparse:
            g.add((pattern, HMO.hasSparsePatternEntities, HMO[x]))
        for photo in photos:
            g.add((mqi, PROV.wasDerivedFrom, photo))
        prop_iris[k] = {}
        for key, cls in PROPERTY_CLASSES.items():
            p = ind(g, C[f"{cls}_{k}"], HMO[cls])
            g.add((rve, HMO.hasHomogenisedMechanicalProperty, p))
            prop_iris[k][key] = str(C[f"{cls}_{k}"])
        rho = ind(g, C[f"MassDensity_{k}"], HMO.MassDensity)
        g.add((rve, HMO.hasHomogenisedMechanicalProperty, rho))
        g.add((rho, SAREF.hasValue, Literal(float(t["mass_density_kg_m3"]), datatype=XSD.float)))
        g.add((rho, RDFS.comment, Literal(
            "Asserted, not derived: HMO has no rule for mass density. " + t["density_note"], lang="en")))
    return g, walls, prop_iris


def undeclared_terms(abox, tbox):
    """HSV, HSTO and HMO terms the individuals use but no ontology declares.

    A misspelt class, property or constant (the pattern entities the HMO
    rules match on) would otherwise just become a new term, and the
    reasoner would accept it silently.
    """
    declared = set(tbox.subjects(RDF.type, None))
    used = set()
    for s, p, o in abox:
        used.add(p)
        if isinstance(o, URIRef):
            used.add(o)
    return sorted(str(t) for t in used
                  if any(str(t).startswith(str(ns)) for ns in (HSV, HSTO, HMO)) and t not in declared)


def domain_range_violations(abox, tbox):
    """Uses of an HSV, HSTO or HMO property outside its declared domain or range.

    OWL does not report these: it infers that the subject or object belongs
    to the domain or range instead, so a unit wrongly linked with
    hsv:contains would silently become an aggregate. Checked here against
    the classes asserted for each individual, closed under rdfs:subClassOf.
    """
    def classes(expr):
        if isinstance(expr, URIRef):
            return {expr}
        members = tbox.value(expr, OWL.unionOf)
        return set(Collection(tbox, members)) if members is not None else set()

    supers = {}

    def closure(c):
        if c not in supers:
            supers[c] = {c}
            for s in tbox.objects(c, RDFS.subClassOf):
                if isinstance(s, URIRef):
                    supers[c] |= closure(s)
        return supers[c]

    both = tbox + abox

    def types(x):
        return set().union(set(), *(closure(t) for t in both.objects(x, RDF.type)))

    problems = set()
    for s, p, o in abox:
        if not any(str(p).startswith(str(ns)) for ns in (HSV, HSTO, HMO)):
            continue
        for role, x, axiom in (("domain", s, RDFS.domain), ("range", o, RDFS.range)):
            if isinstance(x, Literal):
                continue
            for expr in tbox.objects(p, axiom):
                allowed = classes(expr)
                if allowed and not types(x) & allowed:
                    nm = abox.namespace_manager
                    problems.add(f"{p.n3(nm)}: {x.n3(nm)} is outside the {role}")
    return sorted(problems)


def main():
    survey = json.load(open(SURVEY_PATH, encoding="utf-8"))
    classification = json.load(open(CLASSIFICATION_PATH, encoding="utf-8"))
    abox, walls, prop_iris = build(survey, classification)

    kb = rdflib.Graph()
    for path in ONTOLOGIES.values():
        kb.parse(path, format="turtle")
    missing = undeclared_terms(abox, kb)
    if missing:
        raise SystemExit("terms not declared by HSV, HSTO or HMO:\n  " + "\n  ".join(missing))
    misuse = domain_range_violations(abox, kb)
    if misuse:
        raise SystemExit("properties used outside their domain or range:\n  " + "\n  ".join(misuse))
    kb += abox
    print(f"knowledge base: {len(abox)} asserted triples over {len(kb) - len(abox)} ontology triples")

    world = run_pellet(kb, name="castelnuovo_knowledge_graph")
    derived = {k: read_derived(world, str(C[f"MQI_{k}"]), prop_iris[k], f"wall {k}") for k in walls}
    print(f"Pellet: consistent; quality index and properties derived for all {len(derived)} walls")

    engine = engine_route.compute_all(classification)
    by_type = {}
    for k, (_wall, mtype, _photos) in walls.items():
        problems = cross_check({mtype: derived[k]}, {mtype: engine[mtype]})
        if problems:
            raise SystemExit(f"wall {k}: reasoner and engine disagree:\n  " + "\n  ".join(problems))
        by_type.setdefault(mtype, []).append(derived[k])
    for mtype, ds in by_type.items():
        if any(d != ds[0] for d in ds):
            raise SystemExit(f"{mtype}: walls of the same type were derived different values")

    # materialise the derived values in the graph, rounded as the engine does
    for k, d in derived.items():
        for direction, prop in DIRECTION_PROPS.items():
            abox.add((C[f"MQI_{k}"], HMO[prop],
                      Literal(round(d["mqi_total"][direction], ENGINE_DECIMALS["mqi"]), datatype=XSD.float)))
        for key, v in d["mechanical_properties"].items():
            abox.add((URIRef(prop_iris[k][key]), SAREF.hasValue,
                      Literal(round(v, ENGINE_DECIMALS[key]), datatype=XSD.float)))
    abox.add((C.KnowledgeGraph, RDF.type, OWL.Ontology))
    abox.add((C.KnowledgeGraph, RDFS.comment, Literal(
        "Castelnuovo di Porto case study, built on HSV, HSTO and HMO. Quality indices and homogenised "
        "properties were derived by Pellet from the HMO rules (resources/ontologies/hmo.ttl) and "
        "checked against core/ifc_processing/hmo_mqi.py.", lang="en")))
    for path in ONTOLOGIES.values():
        name = os.path.basename(path).split(".")[0]
        abox.add((C.KnowledgeGraph, OWL.imports, URIRef(f"https://w3id.org/{name}")))

    os.makedirs(OUT_DIR, exist_ok=True)
    abox.serialize(os.path.join(OUT_DIR, "knowledge_graph.ttl"), format="turtle", encoding="utf-8")

    note = ("Pellet over the knowledge graph (HSV, HSTO, HMO; HMO rules from "
            f"{ONTOLOGIES['hmo']}), cross-checked against core/ifc_processing/hmo_mqi.py")
    for mtype, ds in by_type.items():
        r = engine[mtype]
        r["mqi_total"] = {d: round(v, ENGINE_DECIMALS["mqi"]) for d, v in ds[0]["mqi_total"].items()}
        for key, v in ds[0]["mechanical_properties"].items():
            r["mechanical_properties"][key] = round(v, ENGINE_DECIMALS[key])
        r["derivation"] = note
    engine_route.write_material_database(engine, os.path.join(OUT_DIR, "material_database.json"))

    print(f"walls per type: { {m: len(v) for m, v in sorted(by_type.items())} }")
    engine_route.print_summary(engine)
    print(f"\nWrote {OUT_DIR}/knowledge_graph.ttl ({len(abox)} triples) and {OUT_DIR}/material_database.json")


if __name__ == "__main__":
    main()
