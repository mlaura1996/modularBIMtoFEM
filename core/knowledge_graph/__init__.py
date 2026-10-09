"""Knowledge graph of a case study: records in a workbook, graph on HSV,
HSTO and HMO, masonry properties derived by Pellet, and a browsable page.

    python -m core.knowledge_graph template <path.xlsx>
    python -m core.knowledge_graph build <case.xlsx> --out <dir> [--bim <bim_elements.json>]
                                         [--site <page dir>] [--photos <photo folder>]

See workbook.py for the records, builder.py for the graph, page.py for the
page.
"""
