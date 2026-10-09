"""
Castelnuovo material database from core/ifc_processing/hmo_mqi.py.

    python docker/opensees/castelnuovo_material_engine.py

Loads resources/survey_data/castelnuovo/masonry_classification.json (the
photo/manuscript-grounded classification of the 4 IFC masonry types), runs
each through the MQI engine and writes output/castelnuovo/
material_database.json: flat JSON keyed by the same material names the IFC
file and core/ifc_processing/data_extractor.py use
("Tufelli_masonry_typeA" etc.), in the same field shape as data_extractor's
Material class, so it can be merged into that pipeline's material_db
without a translation step (see utils.dict_helper.load_material_objects,
which reads exactly this file).

This is the engine route: it needs nothing beyond the Docker image. The
reasoning route, python -m core.knowledge_graph (castelnuovo_knowledge_graph.py), builds the
case-study knowledge graph (HSV, HSTO, HMO), has Pellet derive the same
quantities from the HMO rules, checks them against compute_all() below and
writes the same database from the reasoner's values. The two routes write
the same numbers; only the "_derivation" note differs.
"""
import json
import os
import sys

sys.path.insert(0, "/app")
from core.ifc_processing.material_database import (  # noqa: F401 (re-exported)
    compute_all, print_summary, write_material_database, ENGINE_DERIVATION,
    TENSILE_TO_COMPRESSIVE_RATIO)

CLASSIFICATION_PATH = "resources/survey_data/castelnuovo/masonry_classification.json"
OUT_DIR = "output/castelnuovo"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CLASSIFICATION_PATH) as f:
        classification = json.load(f)

    results = compute_all(classification)
    print_summary(results)
    write_material_database(results, os.path.join(OUT_DIR, "material_database.json"))
    print(f"\nWrote {OUT_DIR}/material_database.json")


if __name__ == "__main__":
    main()
