"""Builds the Castelnuovo di Porto knowledge graph and its page.

    python docker/opensees/castelnuovo_knowledge_graph.py

Kept as the short command for this case study; the work is done by the
generic pipeline, from the case-study workbook:

    python -m core.knowledge_graph build resources/survey_data/castelnuovo/case.xlsx \\
        --out output/castelnuovo --bim resources/survey_data/castelnuovo/bim_elements.json \\
        --site docs/source/_extra/knowledge-graph

The workbook replaced survey_record.json as the record of the survey (see
scripts/migrate_castelnuovo_to_workbook.py for how it was obtained); the
masonry classification is in its MasonryTypes sheet. Needs Java and
owlready2 0.48, rdflib and openpyxl (see resources/ontologies/README.md).
"""
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.knowledge_graph.__main__ import main

if __name__ == "__main__":
    main(["build", "resources/survey_data/castelnuovo/case.xlsx", "--out", "output/castelnuovo",
          "--bim", "resources/survey_data/castelnuovo/bim_elements.json",
          "--site", "docs/source/_extra/knowledge-graph"])
