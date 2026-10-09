"""Builds the knowledge graph of a case study and derives its masonry
properties with the reasoner.

The graph is built from the records of core/knowledge_graph/workbook.py on
the Historic Survey (HSV), Historic Structure (HSTO) and Historic Masonry
(HMO) ontologies:

  HSV   the built context (historic centre, aggregate, structural units),
        the facades and the documents, with the people who acquired,
        processed or authored them
  HSTO  facades as structural parts made of a masonry wall, floors,
        connections between facades, historic openings
  HMO   one masonry wall per facade, with its representative volume
        element, pattern, quality index and properties; and, for every
        variant of a classification, a hypothetical wall characterised the
        same way, so that the reasoner derives the variants too
  FMO   the vulnerabilities recorded for each wall; the reasoner derives
        the behaviour of every wall in each direction from its quality
        index, and the failure mechanisms its vulnerabilities enable

Where the ontologies have no term for something the records hold, a
standard vocabulary is used instead of a term with the wrong domain:
PROV-O for activities, roles and derivation, Dublin Core for dates,
identifiers and part-whole decomposition, FOAF for people and
organisations, SKOS for the masonry types.

run() checks the individuals (every HSV, HSTO and HMO term declared, every
property used within its domain and range), runs Pellet over the
ontologies and the individuals together, checks the derived values against
the Python implementation of the rules, writes them into the graph, and
writes the graph and the material database.
"""
import json
import os

import rdflib
from rdflib import RDF, RDFS, OWL, XSD, Literal, Namespace, URIRef
from rdflib.collection import Collection

from core.ifc_processing.hmo_reasoner import (
    PROPERTY_CLASSES, ENGINE_DECIMALS, cross_check, pattern_entities, read_derived, run_pellet)
from core.ifc_processing.material_database import compute_all, write_material_database

HSV = Namespace("https://w3id.org/hsv#")
HSTO = Namespace("https://w3id.org/hsto#")
HMO = Namespace("https://w3id.org/hmo#")
FMO = Namespace("https://w3id.org/fmo#")
SAREF = Namespace("https://saref.etsi.org/core/")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
CHECKED = (HSV, HSTO, HMO, FMO)
ONTOLOGIES = {"hmo": "resources/ontologies/hmo.ttl", "hsv": "resources/ontologies/hsv.ttl",
              "hsto": "resources/ontologies/hsto.ttl", "fmo": "resources/ontologies/fmo.ttl"}
DIRECTIONS = ("Vertical", "OutOfPlane", "InPlane")
DIRECTION_PROPS = {"vertical": "MQITotalVertical", "out_of_plane": "MQITotalOutOfPlane",
                   "in_plane": "MQITotalInPlane"}
# measured quantities that have an HMO class
MEASURED_CLASSES = {"compressive_strength_MPa": "CompressiveStrength", "young_modulus_MPa": "YoungModulus",
                    "shear_modulus_MPa": "ShearModulus", "density_kg_m3": "MassDensity",
                    "shear_strength_turnsek_cacovic_MPa": "ShearStrengthTC"}
QUANTITY_LABELS = {"compressive_strength_MPa": "compressive strength f_m (MPa)",
                   "tensile_strength_MPa": "tensile strength f_t (MPa)", "cohesion_MPa": "cohesion c (MPa)",
                   "young_modulus_MPa": "Young's modulus E (MPa)", "shear_modulus_MPa": "shear modulus G (MPa)",
                   "shear_strength_turnsek_cacovic_MPa": "shear strength τ₀ (MPa)",
                   "density_kg_m3": "mass density ρ (kg/m³)"}


def ind(g, iri, *classes, label=None):
    g.add((iri, RDF.type, OWL.NamedIndividual))
    for c in classes:
        g.add((iri, RDF.type, c))
    if label:
        g.add((iri, RDFS.label, Literal(label, lang="en")))
    return iri


def _facades_of(photo):
    return [x.strip() for x in str(photo.get("facade") or "").split(";") if x.strip()]


def _strip(s, prefix):
    return s[len(prefix):] if s.startswith(prefix) else s


def _characterise(g, C, k, wall, t, observation, evidence_photos=()):
    """RVE, pattern, units, quality index and property individuals of one wall."""
    rve = ind(g, C[f"RVE_{k}"], HMO.RepresentativeVolumeElement)
    pattern = ind(g, C[f"Pattern_{k}"], HMO.Pattern)
    units = ind(g, C[f"Units_{k}"], HMO.Units)
    mqi = ind(g, C[f"MQI_{k}"], HMO.MasonryQualityIndex)
    g.add((wall, HMO.hasRepresentativeVolumeElement, rve))
    g.add((wall, HMO.hasMasonryQualityIndex, mqi))
    g.add((rve, HMO.hasPattern, pattern))
    dominant, sparse, (lo, hi) = pattern_entities(observation)
    # xsd:float as the range declares: a double would be inconsistent
    g.add((units, HMO.unitsLengthHasMinimumValue, Literal(lo, datatype=XSD.float)))
    g.add((units, HMO.unitsLengthMaximumValue, Literal(hi, datatype=XSD.float)))
    g.add((units, RDFS.comment, Literal(
        f"Representative length range for the '{observation['unit_dimensions']}' category "
        "recorded by the survey, not measured unit lengths.", lang="en")))
    g.add((pattern, HMO.hasDominantPatternEntities, units))
    for x in dominant:
        g.add((pattern, HMO.hasDominantPatternEntities, HMO[x]))
    for x in sparse:
        g.add((pattern, HMO.hasSparsePatternEntities, HMO[x]))
    for photo in evidence_photos:
        g.add((mqi, PROV.wasDerivedFrom, photo))
    props = {}
    for key, cls in PROPERTY_CLASSES.items():
        p = ind(g, C[f"{cls}_{k}"], HMO[cls])
        g.add((rve, HMO.hasHomogenisedMechanicalProperty, p))
        props[key] = str(C[f"{cls}_{k}"])
    rho = ind(g, C[f"MassDensity_{k}"], HMO.MassDensity)
    g.add((rve, HMO.hasHomogenisedMechanicalProperty, rho))
    g.add((rho, SAREF.hasValue, Literal(float(t["mass_density_kg_m3"]), datatype=XSD.float)))
    g.add((rho, RDFS.comment, Literal(
        "Asserted, not derived: HMO has no rule for mass density. " + t.get("density_note", ""), lang="en")))
    return props


def build(case, classification, bim_elements=()):
    """(graph, walls, variant walls, property IRIs, namespace)."""
    proj = case["project"]
    C = Namespace(proj["namespace"])
    g = rdflib.Graph()
    for p, ns in (("", C), ("hsv", HSV), ("hsto", HSTO), ("hmo", HMO), ("fmo", FMO), ("saref", SAREF),
                  ("prov", PROV), ("dcterms", DCT), ("foaf", FOAF), ("skos", SKOS)):
        g.bind(p, ns)

    # --- people, organisations, activities (FOAF, PROV-O) -----------------
    for oid, name in case["organisations"].items():
        ind(g, C[oid], FOAF.Organization)
        g.add((C[oid], FOAF.name, Literal(name)))
    for pid, p in case["people"].items():
        ind(g, C[pid], FOAF.Person)
        g.add((C[pid], FOAF.name, Literal(p["name"])))
        if p.get("affiliation"):
            g.add((C[p["affiliation"]], FOAF.member, C[pid]))
    for aid, a in case["activities"].items():
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
        if a.get("date"):
            g.add((C[aid], DCT.date, Literal(a["date"], datatype=XSD.date)))
        if a.get("start"):
            g.add((C[aid], PROV.startedAtTime, Literal(a["start"], datatype=XSD.dateTime)))
        if a.get("end"):
            g.add((C[aid], PROV.endedAtTime, Literal(a["end"], datatype=XSD.dateTime)))
        if a.get("notes"):
            g.add((C[aid], RDFS.comment, Literal(a["notes"], lang="en")))

    # --- the built context (HSV) ------------------------------------------
    aggregate = ind(g, C[proj["aggregate_id"]], HSV.Aggregate, label=proj.get("aggregate_label"))
    centre = technique = None
    if proj.get("centre_id"):
        centre = ind(g, C[proj["centre_id"]], HSV.HistoricCentre, label=proj.get("centre_label"))
        g.add((centre, HSV.contains, aggregate))
    if proj.get("technique_id"):
        technique = ind(g, C[proj["technique_id"]], HSV.TraditionalConstructionTechnique,
                        label=proj.get("technique_label"))
        if centre is not None:
            g.add((centre, HSV.hasTraditionalConstructionTechnique, technique))

    # --- documents (HSV, PROV-O) --------------------------------------------
    roles = (("authors", HSV.Author, HSV.hasAuthor), ("acquired_by", HSV.Inspector, HSV.acquiredBy),
             ("processed_by", HSV.PostProcesser, HSV.postProcessedBy))
    for did, d in case["documents"].items():
        doc = ind(g, C[did], HSV[d["class"]], label=d["label"])
        for key, cls, prop in roles:
            for pid in d.get(key, []):
                g.add((C[pid], RDF.type, cls)); g.add((doc, prop, C[pid]))
        if d.get("activity"):
            g.add((doc, PROV.wasGeneratedBy, C[d["activity"]]))
        if d.get("used_in"):
            g.add((C[d["used_in"]], PROV.used, doc))
        if d.get("derived_from"):
            g.add((doc, PROV.wasDerivedFrom, C[d["derived_from"]]))
        if d.get("date"):
            g.add((doc, DCT.created, Literal(d["date"], datatype=XSD.date)))
        if d.get("identifier"):
            g.add((doc, DCT.identifier, Literal(d["identifier"])))
        about = d.get("about") or ([] if d["class"] == "Publication" else [proj["aggregate_id"]])
        for x in about:
            g.add((C[x], HSV.hasDocument, doc))

    # --- structural units and their floors (HSV, HSTO) ------------------------
    for uid, u in case["units"].items():
        unit = ind(g, C[uid], HSV.StructuralUnit, label=u["label"])
        g.add((aggregate, HSV.contains, unit))
        if u.get("floor"):
            f = u["floor"]
            floor = ind(g, C["Floor_" + _strip(uid, "Unit_")], HSTO[f["kind"]], label=f.get("label"))
            g.add((floor, HSTO.hasAccessibility, Literal(bool(f.get("accessible")))))
            if f.get("note"):
                g.add((floor, RDFS.comment, Literal(f["note"], lang="en")))
            # HSV and HSTO have no property relating a unit to its parts
            g.add((unit, DCT.hasPart, floor))

    # --- masonry types (SKOS) -----------------------------------------------
    for name, t in classification["types"].items():
        mt = ind(g, C[name], SKOS.Concept, label=name)
        g.add((mt, SKOS.definition, Literal(t["description"], lang="en")))
        for flag in t.get("flags", []):
            g.add((mt, RDFS.comment, Literal(flag, lang="en")))
        evidence = t.get("evidence", {})
        for param, note in (evidence.items() if isinstance(evidence, dict) else []):
            text = note if param == "general" else f"{param.replace('_', ' ')}: {note}"
            g.add((mt, SKOS.note, Literal(text, lang="en")))

    # --- BIM elements of each masonry type ------------------------------------
    # linked by the material name, as the conversion to the numerical model is
    bim_doc = C[proj["bim_document"]] if proj.get("bim_document") else None
    for e in bim_elements:
        mtype = next((m for m in e.get("materials", []) if m in classification["types"]), None)
        if mtype is None or bim_doc is None:
            continue
        el = ind(g, C["IFC_" + e["global_id"].replace("$", "-")], label=f"{e['ifc_class']} {e['name']}".strip())
        g.add((el, DCT.identifier, Literal(e["global_id"])))
        g.add((el, DCT.isPartOf, bim_doc))
        g.add((el, DCT.type, C[mtype]))

    # --- BIM elements of each facade, where the editor has recorded them --------
    for fid, f in case["facades"].items():
        for guid in f.get("elements", []):
            el = C["IFC_" + guid.replace("$", "-")]
            g.add((el, DCT.identifier, Literal(guid)))
            if bim_doc is not None:
                g.add((el, DCT.isPartOf, bim_doc))
            g.add((el, DCT.isPartOf, C[fid]))
            g.add((el, DCT.type, C[f["masonry_type"]]))

    # --- photographs: of one or more facades, or of the aggregate ---------------
    people = set(case["people"])
    for phid, ph in case["photos"].items():
        photo = ind(g, C[phid], HSV.Photo, label=ph.get("label") or None)
        g.add((photo, DCT.identifier, Literal(ph["file"])))
        if ph.get("taken"):
            g.add((photo, DCT.created, Literal(ph["taken"], datatype=XSD.dateTime)))
        takers = ph.get("acquired_by") or (case["activities"][ph["activity"]]["people"] if ph.get("activity") else [])
        for pid in (x for x in takers if x in people):     # HSV Inspector is a person
            g.add((C[pid], RDF.type, HSV.Inspector))
            g.add((photo, HSV.acquiredBy, C[pid]))
        if ph.get("activity"):
            g.add((photo, PROV.wasGeneratedBy, C[ph["activity"]]))
        if ph.get("source"):
            g.add((photo, DCT.source, Literal(ph["source"])))
        for x in _facades_of(ph) or [proj["aggregate_id"]]:
            g.add((C[x], HSV.hasDocument, photo))
            g.add((photo, HSV.isDocumentOf, C[x]))

    # --- facades and their walls (HSV, HSTO, HMO) -------------------------------
    walls = {}
    for fid, f in case["facades"].items():
        k = _strip(fid, "Facade_")
        facade = ind(g, C[fid], HSV.Facade, HSTO.Facade, label=f["label"])
        g.add((C[f["unit"]], DCT.hasPart, facade))
        if technique is not None:
            g.add((facade, HSTO.isBuiltWithTraditionalConstructionTechnique, technique))
        photos = [C[phid] for phid, ph in case["photos"].items() if fid in _facades_of(ph)]
        wall = ind(g, C[f"Wall_{k}"], HMO.MasonryWall, label=f"Masonry wall of {f['label'][0].lower() + f['label'][1:]}")
        g.add((facade, HSTO.isMadeOf, wall))
        g.add((wall, DCT.type, C[f["masonry_type"]]))
        walls[k] = (wall, f["masonry_type"], photos)

    for cid, cn in case["connections"].items():
        conn = ind(g, C[cid], HSTO[cn["kind"] or "Connection"], label=cn.get("label"))
        if cn.get("quality"):
            g.add((conn, HSTO.hasConnectionQuality, Literal(cn["quality"])))
        for side in ("part_a", "part_b"):
            g.add((C[cn[side]], HSTO.isConnectedTo, conn))
    for oid, o in case["openings"].items():
        opening = ind(g, C[oid], HSTO.HistoricOpening, label=o["label"])
        g.add((C[o["facade"]], HSTO.hasHistoricOpening, opening))
    # vulnerabilities of the facade walls (FMO); the evidence stays on the wall
    for v in case.get("vulnerabilities", []):
        wall = C["Wall_" + _strip(v["facade"], "Facade_")]
        g.add((wall, FMO.hasVulnerability, FMO[v["vulnerability"]]))
        if v.get("evidence"):
            g.add((wall, RDFS.comment, Literal(f"{v['vulnerability']}: {v['evidence']}", lang="en")))

    # --- HMO characterisation: facade walls, then hypothetical variant walls ---
    prop_iris = {}
    for k, (wall, mtype, photos) in walls.items():
        t = classification["types"][mtype]
        prop_iris[k] = _characterise(g, C, k, wall, t, t["observation"], photos)
    variants = {}
    for name, t in classification["types"].items():
        for vname, change in t.get("variants", {}).items():
            k = f"{name}_{vname}"
            wall = ind(g, C[f"VariantWall_{k}"], HMO.MasonryWall,
                       label=f"{name}, {vname} variant (hypothetical wall)")
            g.add((wall, DCT.type, C[name]))
            g.add((wall, SKOS.note, Literal(
                f"Hypothetical wall, not part of the building: the {vname} variant of {name}, with "
                + ", ".join(f"{p.replace('_', ' ')} {v}" for p, v in change.items()) + ".", lang="en")))
            prop_iris[k] = _characterise(g, C, k, wall, t, {**t["observation"], **change})
            variants[k] = (wall, name, vname, {**t["observation"], **change})

    # --- measured properties, to compare the derived ones with -----------------
    for i, m in enumerate(case.get("measured", []), start=1):
        cls = MEASURED_CLASSES.get(m["quantity"])
        iri = ind(g, C[f"Measured_{i:02d}"], *( [HMO[cls]] if cls else []),
                  label=f"Measured {QUANTITY_LABELS.get(m['quantity'], m['quantity'].replace('_', ' '))}, "
                        f"{m['basis']}")
        g.add((iri, SAREF.hasValue, Literal(float(m["value"]), datatype=XSD.float)))
        g.add((iri, DCT.subject, C[m["masonry_type"]]))
        g.add((iri, DCT.source, Literal(m["source"])))
        g.add((iri, SKOS.note, Literal(f"Basis: {m['basis']}", lang="en")))
    return g, walls, variants, prop_iris, C


def undeclared_terms(abox, tbox):
    """HSV, HSTO and HMO terms the individuals use but no ontology declares."""
    declared = set(tbox.subjects(RDF.type, None))
    used = set()
    for s, p, o in abox:
        used.add(p)
        if isinstance(o, URIRef):
            used.add(o)
    return sorted(str(t) for t in used
                  if any(str(t).startswith(str(ns)) for ns in CHECKED) and t not in declared)


def domain_range_violations(abox, tbox):
    """Uses of an HSV, HSTO or HMO property outside its declared domain or range.

    OWL does not report these: it infers that the subject or object belongs
    to the domain or range instead, so a unit wrongly linked with
    hsv:contains would silently become an aggregate.
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
        if not any(str(p).startswith(str(ns)) for ns in CHECKED):
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


def run(case, classification, out_dir, bim_elements=(), ontologies=ONTOLOGIES, log=print):
    """Builds, checks and reasons; writes knowledge_graph.ttl and material_database.json."""
    abox, walls, variants, prop_iris, C = build(case, classification, bim_elements)
    kb = rdflib.Graph()
    for path in ontologies.values():
        kb.parse(path, format="turtle")
    missing = undeclared_terms(abox, kb)
    if missing:
        raise SystemExit("terms not declared by HSV, HSTO or HMO:\n  " + "\n  ".join(missing))
    misuse = domain_range_violations(abox, kb)
    if misuse:
        raise SystemExit("properties used outside their domain or range:\n  " + "\n  ".join(misuse))
    kb += abox
    log(f"knowledge base: {len(abox)} asserted triples over {len(kb) - len(abox)} ontology triples")

    world = run_pellet(kb, name=f"{case['project']['id']}_knowledge_graph")
    derived = {k: read_derived(world, str(C[f"MQI_{k}"]), prop_iris[k], f"wall {k}") for k in prop_iris}
    log(f"Pellet: consistent; quality index and properties derived for {len(walls)} walls "
        f"and {len(variants)} variants")

    # FMO: behaviour in each direction and the mechanisms the vulnerabilities enable
    has_behaviour, has_mechanism = world[str(FMO.hasBehaviour)], world[str(FMO.hasOccurringMechanism)]
    fmo_derived = {}
    for k, (wall, *_rest) in list(walls.items()) + list(variants.items()):
        behaviours = sorted(b.name for b in has_behaviour[world[str(wall)]])
        for d in DIRECTIONS:
            n = sum(b.endswith(f"{d}Behaviour") for b in behaviours)
            if n != 1:
                raise SystemExit(f"{k}: {n} {d} behaviours derived ({behaviours}); expected exactly one")
        mechanisms = sorted(m.name for m in has_mechanism[world[str(wall)]])
        fmo_derived[k] = (wall, behaviours, mechanisms)

    # every derived value must agree with the Python implementation of the rules
    engine = compute_all(classification)
    variant_cls = {"types": {k: {**classification["types"][name], "observation": obs}
                             for k, (_w, name, _v, obs) in variants.items()}}
    engine.update(compute_all(variant_cls) if variants else {})
    by_type = {}
    for k, d in derived.items():
        name = walls[k][1] if k in walls else k
        problems = cross_check({name: d}, {name: engine[name]})
        if problems:
            raise SystemExit(f"{k}: reasoner and engine disagree:\n  " + "\n  ".join(problems))
        if k in walls:
            by_type.setdefault(name, []).append(d)
    for mtype, ds in by_type.items():
        if any(d != ds[0] for d in ds):
            raise SystemExit(f"{mtype}: walls of the same type were derived different values")

    for k, d in derived.items():
        for direction, prop in DIRECTION_PROPS.items():
            abox.add((C[f"MQI_{k}"], HMO[prop],
                      Literal(round(d["mqi_total"][direction], ENGINE_DECIMALS["mqi"]), datatype=XSD.float)))
        for key, v in d["mechanical_properties"].items():
            abox.add((URIRef(prop_iris[k][key]), SAREF.hasValue,
                      Literal(round(v, ENGINE_DECIMALS[key]), datatype=XSD.float)))
    for k, (wall, behaviours, mechanisms) in fmo_derived.items():
        for b in behaviours:
            abox.add((wall, FMO.hasBehaviour, FMO[b]))
        for m in mechanisms:
            abox.add((wall, FMO.hasOccurringMechanism, FMO[m]))
    kg_iri = C.KnowledgeGraph
    abox.add((kg_iri, RDF.type, OWL.Ontology))
    abox.add((kg_iri, RDFS.label, Literal(case["project"].get("title", ""), lang="en")))
    abox.add((kg_iri, RDFS.comment, Literal(
        (case["project"].get("description", "") + " ").lstrip()
        + "Built on HSV, HSTO, HMO and FMO. Quality indices, homogenised properties and behaviours were "
          "derived by Pellet from the HMO and FMO rules (resources/ontologies/) and checked against "
          "core/ifc_processing/hmo_mqi.py.", lang="en")))
    for name in ontologies:
        abox.add((kg_iri, OWL.imports, URIRef(f"https://w3id.org/{name}")))
    if case["project"].get("software_doi"):
        abox.add((kg_iri, DCT.references, URIRef("https://doi.org/" + case["project"]["software_doi"])))

    os.makedirs(out_dir, exist_ok=True)
    abox.serialize(os.path.join(out_dir, "knowledge_graph.ttl"), format="turtle", encoding="utf-8")
    note = ("Pellet over the knowledge graph (HSV, HSTO, HMO; HMO rules from "
            f"{ontologies['hmo']}), cross-checked against core/ifc_processing/hmo_mqi.py")
    db = {}
    for mtype in [m for m in classification["types"] if m in by_type]:   # classification order
        ds = by_type[mtype]
        r = engine[mtype]
        r["mqi_total"] = {d: round(v, ENGINE_DECIMALS["mqi"]) for d, v in ds[0]["mqi_total"].items()}
        for key, v in ds[0]["mechanical_properties"].items():
            r["mechanical_properties"][key] = round(v, ENGINE_DECIMALS[key])
        r["derivation"] = note
        db[mtype] = r
    write_material_database(db, os.path.join(out_dir, "material_database.json"))
    log(f"walls per type: { {m: len(v) for m, v in sorted(by_type.items())} }")
    for name, r in db.items():
        m = r["mechanical_properties"]
        log(f"  {name}: fm={m['compressive_strength_MPa']} E={m['young_modulus_MPa']} "
            f"G={m['shear_modulus_MPa']} tau0={m['shear_strength_turnsek_cacovic_MPa']}")
    for k, (_w, name, vname, _obs) in variants.items():
        m = derived[k]["mechanical_properties"]
        log(f"  {name} ({vname}): fm={m['compressive_strength_MPa']:.3f} E={m['young_modulus_MPa']:.1f}")
    for k, (_w, behaviours, mechanisms) in fmo_derived.items():
        if k in walls:
            log(f"  {k}: {', '.join(b.replace('Behaviour', '') for b in behaviours)}"
                + (f" | mechanisms: {', '.join(mechanisms)}" if mechanisms else ""))
    log(f"wrote {out_dir}/knowledge_graph.ttl ({len(abox)} triples) and {out_dir}/material_database.json")
    return abox
