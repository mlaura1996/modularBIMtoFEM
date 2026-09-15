# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

project = "openBIMtoFEM"
copyright = "2026, Maria Laura Leonardi"
author = "Maria Laura Leonardi"
release = "chapter7-castelnuovo"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
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
html_title = "openBIMtoFEM documentation"
html_logo = "_static/images/open_bim_to_fem_logo.png"

# Allow importing the repository's own packages so autodoc can pull
# docstrings (core/, external/, models/, utils/) - the repo root is one
# level above docs/source/.
import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

# -- autodoc ------------------------------------------------------------
# The real pipeline needs gmsh, OpenCASCADE (via pythonocc-core),
# ifcopenshell and openseespy - compiled/C-extension packages that only
# exist inside the Docker image (docker/opensees/Dockerfile), not in a
# plain "pip install sphinx" environment. autodoc still needs to IMPORT
# every module to read its docstrings, so without mocking these out, the
# whole API reference would fail to build anywhere except inside that
# image. Mocking replaces each package with a stand-in that accepts any
# attribute access (gmsh.model.mesh.generate(), etc. all resolve without
# error) purely for the purpose of reading source and docstrings -
# nothing mocked is ever actually called. numpy/pandas/matplotlib are
# NOT mocked: they are plain `pip install`, no compiler needed, so the
# docs environment installs them for real and autodoc can report their
# actual return types where relevant.
autodoc_mock_imports = ["gmsh", "OCC", "ifcopenshell", "openseespy"]
autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
napoleon_google_docstring = True
napoleon_numpy_docstring = False
