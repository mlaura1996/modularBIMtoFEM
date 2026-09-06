# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

project = "modularBIMtoFEM"
copyright = "2026, Maria Laura Leonardi"
author = "Maria Laura Leonardi"
release = "chapter7-castelnuovo"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "sphinx_design",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# -- HTML output, matching the OpenSees documentation site's own theme -----
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 3,
    "sticky_navigation": True,
}
html_title = "modularBIMtoFEM — Chapter 7 documentation"
html_logo = "_static/images/open_bim_to_fem_logo.png"

# Allow importing the repository's own packages so autodoc can pull
# docstrings (core/, external/, models/, utils/) - the repo root is one
# level above docs/source/.
import os
import sys

sys.path.insert(0, os.path.abspath("../.."))
