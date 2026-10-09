"""Builds the browsable page of a case-study knowledge graph.

    build_page(<knowledge_graph.ttl>, <page dir>, photos_dir=None)
    (or: python -m core.knowledge_graph build ... --site <page dir>)

Reads the graph written by core/knowledge_graph/builder.py, and the three
ontologies in resources/ontologies/ for labels, and writes a self-contained
page to <page dir>/index.html with a copy of the graph to download. Under
docs/source/_extra/ the page is published with the documentation.

The page has an interactive view of the graph, a 3D view of the BIM model
if <page dir>/bim/model.glb exists (scripts/export_bim_for_web.py), and
tables of the same content: facades and their walls, connections, masonry
types, derived and measured properties, documents, people and activities.
Everything is generated from the graph, so what the page shows is what the
graph says.

Photographs. With photos_dir pointing at the folder the photographs'
dcterms:identifier paths are relative to, each is written as a thumbnail
and a larger view to <page dir>/photos/, resized and saved without
metadata. Without it, images already there are reused.

Needs rdflib, and Pillow for the photographs.
"""
import html
import json
import os
import shutil
from collections import defaultdict

import rdflib
from rdflib import RDF, RDFS, OWL, Literal, URIRef

ONTOLOGIES = ["resources/ontologies/hsv.ttl", "resources/ontologies/hsto.ttl",
              "resources/ontologies/hmo.ttl", "resources/ontologies/fmo.ttl"]
THUMB_PX, LARGE_PX = 320, 1000
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page_template.html")

VOCAB = {
    "hsv": "https://w3id.org/hsv#",
    "hsto": "https://w3id.org/hsto#",
    "hmo": "https://w3id.org/hmo#",
    "fmo": "https://w3id.org/fmo#",
    "saref": "https://saref.etsi.org/core/",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdfs": str(RDFS),
    "owl": str(OWL),
}
HSV, HSTO, HMO, FMO = (rdflib.Namespace(VOCAB[p]) for p in ("hsv", "hsto", "hmo", "fmo"))
SAREF, PROV, DCT = (rdflib.Namespace(VOCAB[p]) for p in ("saref", "prov", "dcterms"))
FOAF, SKOS = rdflib.Namespace(VOCAB["foaf"]), rdflib.Namespace(VOCAB["skos"])

# node groups, in legend order: (key, label, shown by default)
GROUPS = [
    ("context", "Built context (HSV)", True),
    ("facade", "Façades (HSV, HSTO)", True),
    ("structure", "Floors, openings, connections (HSTO)", True),
    ("wall", "Masonry walls (HMO)", True),
    ("type", "Masonry types", True),
    ("document", "Documents (HSV)", True),
    ("activity", "Activities", True),
    ("agent", "People and organisations", True),
    ("photo", "Photographs (HSV)", False),
    ("bim", "BIM elements (IFC)", False),
    ("variant", "Variant walls (hypothetical)", False),
    ("measured", "Measured properties", False),
    ("hmo", "Quality index and properties (HMO)", False),
    ("fmo", "Behaviour, vulnerabilities, mechanisms (FMO)", True),
    ("constant", "Pattern entities (HMO)", False),
]
PROPERTY_CLASSES = {"CompressiveStrength": ("f_c", "MPa"), "YoungModulus": ("E", "MPa"),
                    "ShearModulus": ("G", "MPa"), "ShearStrengthTC": ("τ₀", "MPa"),
                    "MassDensity": ("ρ", "kg/m³")}
STRUCTURE = {HSTO.TimberFloor, HSTO.Vault, HSTO.HorizontalStructure, HSTO.HistoricOpening,
             HSTO.Connection, HSTO.Quoin, HSTO.Tie}


def build_page(kg_path, out_dir, photos_dir=None, ontologies=ONTOLOGIES, log=print):
    kg = rdflib.Graph().parse(kg_path, format="turtle")
    onto = rdflib.Graph()
    for path in ontologies:
        onto.parse(path, format="turtle")
    kg_iri = next(kg.subjects(RDF.type, OWL.Ontology))
    ns = dict(VOCAB, **{"": str(kg_iri)[:-len("KnowledgeGraph")]})

    def curie(term):
        s = str(term)
        best = max((p for p, n in ns.items() if s.startswith(n)), key=lambda p: len(ns[p]), default=None)
        return f"{best}:{s[len(ns[best]):]}" if best is not None else s

    def local(term):
        return curie(term).split(":", 1)[1]

    def label(term):
        for g in (kg, onto):
            for lab in g.objects(term, RDFS.label):
                if not isinstance(lab, Literal) or lab.language in (None, "en"):
                    return str(lab)
        name = kg.value(term, FOAF.name)
        return str(name) if name else local(term)

    def types(term):
        return sorted({t for t in kg.objects(term, RDF.type) if t != OWL.NamedIndividual}, key=str)

    bim_docs = set(kg.subjects(RDF.type, HSV.BuildingInformationModel))

    def is_bim_element(term):
        return any((term, DCT.isPartOf, d) in kg for d in bim_docs)

    def group(term):
        ts = set(types(term))
        if term in ts or term == kg_iri or ts & {PROV.Association, PROV.Role}:
            return None
        if is_bim_element(term):
            return "bim"
        if HSV.Photo in ts:
            return "photo"
        if ts & {HSV.Facade, HSTO.Facade}:
            return "facade"
        if ts & {HSV.HistoricCentre, HSV.Aggregate, HSV.StructuralUnit, HSV.TraditionalConstructionTechnique}:
            return "context"
        if ts & STRUCTURE:
            return "structure"
        if HMO.MasonryWall in ts:
            return "wall" if (None, HSTO.isMadeOf, term) in kg else "variant"
        if SKOS.Concept in ts:
            return "type"
        if ts & {FOAF.Person, FOAF.Organization}:
            return "agent"
        if PROV.Activity in ts:
            return "activity"
        if (term, DCT.subject, None) in kg and (term, SAREF.hasValue, None) in kg:
            return "measured"
        if any(str(t).startswith(VOCAB["hsv"]) for t in ts):
            return "document"
        if any(str(t).startswith(VOCAB["hmo"]) for t in ts):
            return "hmo"
        if str(term).startswith(VOCAB["fmo"]):
            return "fmo"
        if str(term).startswith(VOCAB["hmo"]):
            return "constant"
        return None

    images = _photo_images(kg, out_dir, photos_dir, local)

    # --- graph view ------------------------------------------------------------
    nodes, edges = {}, []

    def add_node(term):
        key = curie(term)
        if key in nodes:
            return key
        g = group(term)
        if g is None:
            return None
        literals = defaultdict(list)
        for p, o in kg.predicate_objects(term):
            if isinstance(o, Literal) and p != RDFS.label:
                literals[curie(p)].append(str(o))
        nodes[key] = {"id": key, "label": label(term), "group": g,
                      "types": [curie(t) for t in types(term)] or
                               ({"bim": ["IFC element of the BIM model"], "fmo": ["FMO individual"]}.get(g, ["hmo constant"])),
                      "literals": dict(literals)}
        if key in images:
            nodes[key]["img"], nodes[key]["large"] = images[key]
        return key

    for s, p, o in kg:
        if p == RDF.type or not isinstance(o, URIRef) or p in (OWL.imports, DCT.references):
            continue
        a, b = add_node(s), add_node(o)
        if a and b:
            edges.append({"from": a, "to": b, "label": curie(p)})
    for s in set(kg.subjects(RDF.type, OWL.NamedIndividual)):
        add_node(s)

    # --- tables ------------------------------------------------------------------
    def wall_values(wall, with_mqi=True):
        out = {}
        if with_mqi:
            mqi = kg.value(wall, HMO.hasMasonryQualityIndex)
            for direction, prop in (("MQI vertical", "MQITotalVertical"),
                                    ("MQI out of plane", "MQITotalOutOfPlane"),
                                    ("MQI in plane", "MQITotalInPlane")):
                v = kg.value(mqi, HMO[prop])
                out[direction] = float(v) if v is not None else None
        rve = kg.value(wall, HMO.hasRepresentativeVolumeElement)
        found = {}
        for prop in kg.objects(rve, HMO.hasHomogenisedMechanicalProperty):
            for t in kg.objects(prop, RDF.type):
                if local(t) in PROPERTY_CLASSES:
                    v = kg.value(prop, SAREF.hasValue)
                    found[local(t)] = float(v) if v is not None else None
        for cls, (sym, unit) in PROPERTY_CLASSES.items():   # fixed column order
            out[f"{sym} ({unit})"] = found.get(cls)
        return out

    facades = []
    for f in sorted(kg.subjects(RDF.type, HSTO.Facade), key=str):
        wall = kg.value(f, HSTO.isMadeOf)
        unit = next(kg.subjects(DCT.hasPart, f), None)
        photos = sorted(o for o in kg.objects(f, HSV.hasDocument) if (o, RDF.type, HSV.Photo) in kg)
        row = {"Façade": label(f).replace("Facade", "Façade"), "_id": curie(f),
               "Unit": local(unit).replace("Unit_", "") if unit else "",
               "Masonry type": label(kg.value(wall, DCT.type)), "_wall": curie(wall),
               "Photographs": len(photos)}
        behaviours = {str(b).split("#")[-1] for b in kg.objects(wall, FMO.hasBehaviour)}
        row["Behaviour"] = [f"{d}: {next((q for q in ('Inadequate', 'Average', 'Good') if f'{q}{key}Behaviour' in behaviours), '–').lower()}"
                            for d, key in (("vertical", "Vertical"), ("out of plane", "OutOfPlane"), ("in plane", "InPlane"))]
        row["Vulnerabilities"] = sorted(label(v) for v in kg.objects(wall, FMO.hasVulnerability))
        row["Expected mechanisms"] = sorted(label(m) for m in kg.objects(wall, FMO.hasOccurringMechanism))
        row.update(wall_values(wall))
        row["_photos"] = [{"file": str(kg.value(ph, DCT.identifier)),
                           "taken": str(kg.value(ph, DCT.created) or ""),
                           "label": str(kg.value(ph, RDFS.label) or ""),
                           "source": str(kg.value(ph, DCT.source) or ""),
                           "img": images.get(curie(ph), (None, None))[0],
                           "large": images.get(curie(ph), (None, None))[1]} for ph in photos]
        facades.append(row)

    facade_set = set(kg.subjects(RDF.type, HSTO.Facade))
    other_photos = []
    for ph in sorted(kg.subjects(RDF.type, HSV.Photo), key=str):
        if any(x in facade_set for x in kg.objects(ph, HSV.isDocumentOf)) or curie(ph) not in images:
            continue
        other_photos.append({"file": str(kg.value(ph, DCT.identifier)), "taken": "",
                             "label": str(kg.value(ph, RDFS.label) or ""),
                             "source": str(kg.value(ph, DCT.source) or ""),
                             "img": images[curie(ph)][0], "large": images[curie(ph)][1]})

    connections = []
    for c in sorted({c for _, _, c in kg.triples((None, HSTO.isConnectedTo, None))}, key=str):
        connections.append({"Connection": label(c), "_id": curie(c),
                            "Kind": ", ".join(local(t) for t in types(c)),
                            "Between": [label(f).replace("Facade", "Façade") for f in kg.subjects(HSTO.isConnectedTo, c)],
                            "Quality": "; ".join(str(q) for q in kg.objects(c, HSTO.hasConnectionQuality))})

    mtypes, comparison = [], []
    for t in sorted(kg.subjects(RDF.type, SKOS.Concept), key=str):
        walls = sorted((w for w in kg.subjects(DCT.type, t)
                        if (w, RDF.type, HMO.MasonryWall) in kg and (None, HSTO.isMadeOf, w) in kg), key=str)
        variants = sorted((w for w in kg.subjects(DCT.type, t)
                           if (w, RDF.type, HMO.MasonryWall) in kg and (None, HSTO.isMadeOf, w) not in kg), key=str)
        bim_elements = [e for e in kg.subjects(DCT.type, t) if is_bim_element(e)]
        fac = [label(f).replace("Facade", "Façade") for w in walls for f in kg.subjects(HSTO.isMadeOf, w)]
        entities = []
        if walls or variants:
            rve = kg.value((walls or variants)[0], HMO.hasRepresentativeVolumeElement)
            pat = kg.value(rve, HMO.hasPattern)
            for p, kind in ((HMO.hasDominantPatternEntities, "dominant"),
                            (HMO.hasSparsePatternEntities, "sparse")):
                for e in kg.objects(pat, p):
                    if str(e).startswith(VOCAB["hmo"]):
                        entities.append(f"{local(e)} ({kind})")
                    else:
                        lo = kg.value(e, HMO.unitsLengthHasMinimumValue)
                        hi = kg.value(e, HMO.unitsLengthMaximumValue)
                        entities.append(f"unit length {float(lo):g}–{float(hi):g} cm")
        mtypes.append({"Type": label(t), "_id": curie(t),
                       "Description": str(kg.value(t, SKOS.definition) or ""),
                       "Façades": ", ".join(fac), "BIM elements": len(bim_elements),
                       "Pattern entities": sorted(entities),
                       "Evidence": sorted(str(n) for n in kg.objects(t, SKOS.note)),
                       "Flags": [str(c) for c in kg.objects(t, RDFS.comment)]})
        measured = [m for m in kg.subjects(DCT.subject, t) if (m, SAREF.hasValue, None) in kg]
        if variants or measured:
            derived = [{"Case": "Derived, as classified", **wall_values(walls[0], with_mqi=False)}] if walls else []
            for v in variants:
                derived.append({"Case": "Derived, " + label(v).split(", ", 1)[-1].replace(" (hypothetical wall)", ""),
                                **wall_values(v, with_mqi=False), "_id": curie(v)})
            comparison.append({
                "type": label(t), "type_id": curie(t), "derived": derived,
                "measured": [{"Quantity": label(m).replace("Measured ", ""), "_id": curie(m),
                              "Value": float(kg.value(m, SAREF.hasValue)),
                              "Source": str(kg.value(m, DCT.source) or "")} for m in sorted(measured, key=str)]})

    roles = {HSV.acquiredBy: "acquired by", HSV.postProcessedBy: "processed by", HSV.hasAuthor: "author"}
    documents = []
    for d in sorted({s for s, _, o in kg.triples((None, RDF.type, None)) if group(s) == "document"}, key=str):
        people = [f"{label(p)} ({r})" for prop, r in roles.items() for p in kg.objects(d, prop)]
        documents.append({
            "Document": label(d), "_id": curie(d),
            "Kind": ", ".join(local(t) for t in types(d)),
            "Date": str(kg.value(d, DCT.created) or ""),
            "Identifier": str(kg.value(d, DCT.identifier) or ""),
            "Derived from": ", ".join(label(x) for x in kg.objects(d, PROV.wasDerivedFrom)),
            "Produced in": ", ".join(label(x) for x in kg.objects(d, PROV.wasGeneratedBy)),
            "Used in": ", ".join(label(a) for a in kg.subjects(PROV.used, d)),
            "People": people})

    activities = []
    for a in sorted(kg.subjects(RDF.type, PROV.Activity), key=str):
        start, end = kg.value(a, PROV.startedAtTime), kg.value(a, PROV.endedAtTime)
        when = str(kg.value(a, DCT.date) or "")
        if start and end:
            when = f"{when} ({str(start)[11:16]}–{str(end)[11:16]} UTC)"
        activities.append({"Activity": label(a), "_id": curie(a), "Date": when,
                           "People": [label(p) for p in kg.objects(a, PROV.wasAssociatedWith)],
                           "Notes": "; ".join(str(c) for c in kg.objects(a, RDFS.comment))})

    people = []
    for p in sorted(kg.subjects(RDF.type, FOAF.Person), key=lambda x: label(x)):
        org = next(kg.subjects(FOAF.member, p), None)
        person_roles = [f"{local(t)} (HSV)" for t in types(p) if str(t).startswith(VOCAB["hsv"])]
        for assoc in kg.subjects(PROV.agent, p):
            activity = next(kg.subjects(PROV.qualifiedAssociation, assoc), None)
            for role in kg.objects(assoc, PROV.hadRole):
                person_roles.append(f"{label(role)} ({label(activity)})" if activity else label(role))
        people.append({"Person": label(p), "_id": curie(p),
                       "Organisation": str(kg.value(org, FOAF.name)) if org else "",
                       "Roles": person_roles,
                       "Activities": [label(a) for a in kg.subjects(PROV.wasAssociatedWith, p)]})

    doi = next((str(r) for r in kg.objects(kg_iri, DCT.references)), None)
    data = {
        "groups": [{"key": k, "label": l, "visible": v} for k, l, v in GROUPS],
        "nodes": list(nodes.values()), "edges": edges,
        "facades": facades, "connections": connections, "types": mtypes, "comparison": comparison,
        "documents": documents, "activities": activities, "people": people, "other_photos": other_photos,
        "bim": {"glb": "bim/model.glb" if os.path.exists(os.path.join(out_dir, "bim", "model.glb")) else None,
                "types": {label(t): curie(t) for t in sorted(kg.subjects(RDF.type, SKOS.Concept), key=str)},
                "elements": {str(kg.value(e, DCT.identifier)): curie(e)
                             for e in kg.subjects(DCT.isPartOf, None) if is_bim_element(e)}},
        "stats": {"triples": len(kg), "nodes": len(nodes), "edges": len(edges)},
        "note": str(kg.value(kg_iri, RDFS.comment) or ""),
    }

    title = str(kg.value(kg_iri, RDFS.label) or "Knowledge graph")
    description = str(kg.value(kg_iri, RDFS.comment) or "").split(" Built on HSV")[0]
    page = open(TEMPLATE, encoding="utf-8").read()
    for key, value in (("__TITLE__", html.escape(title)), ("__DESCRIPTION__", html.escape(description)),
                       ("__DOI__", html.escape(doi or "")), ("__DOI_DISPLAY__", "" if doi else "none")):
        page = page.replace(key, value)
    os.makedirs(out_dir, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(page.replace("/*__DATA__*/null", payload))
    shutil.copyfile(kg_path, os.path.join(out_dir, "knowledge_graph.ttl"))
    log(f"wrote {out_dir}/index.html: {len(nodes)} nodes, {len(edges)} edges, {len(facades)} facades, "
        f"{len(documents)} documents, {len(images)} photographs with images")


def _photo_images(kg, out_dir, src_dir, local):
    """{photo curie-less key: (thumbnail, large view)} relative to out_dir."""
    out = os.path.join(out_dir, "photos")
    images = {}
    if src_dir:
        from PIL import Image, ImageOps
        os.makedirs(out, exist_ok=True)
    for ph in sorted(kg.subjects(RDF.type, HSV.Photo), key=str):
        name = local(ph)
        thumb, large = f"photos/{name}.jpg", f"photos/{name}_large.jpg"
        if src_dir:
            src = os.path.join(src_dir, str(kg.value(ph, DCT.identifier)))
            if not os.path.exists(src):
                raise SystemExit(f"photograph not found: {src}")
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            for px, rel, q in ((THUMB_PX, thumb, 70), (LARGE_PX, large, 72)):
                copy = im.copy()
                copy.thumbnail((px, px))
                copy.save(os.path.join(out_dir, rel), "JPEG", quality=q, optimize=True)  # no metadata
        if os.path.exists(os.path.join(out_dir, thumb)):
            images[":" + name] = (thumb, large)
    return images
