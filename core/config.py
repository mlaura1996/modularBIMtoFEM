# IFC OpenShell
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element

# OpenCascade (OCC)
import OCC.Core.TopoDS
from OCC.Core.BRep import BRep_Builder
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib_Add
from OCC.Core.TopoDS import TopoDS_Compound, TopoDS_Shape, TopoDS_Iterator
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCC.Display.SimpleGui import init_display
from OCC.Core.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCC.Core.Interface import Interface_Static_SetCVal
from OCC.Core.STEPConstruct import *
from OCC.Core.TCollection import TCollection_HAsciiString
from OCC.Extend.DataExchange import read_step_file_with_names_colors
import OCC.Core.AIS
import OCC.Core.XCAFDoc
import OCC.Display.SimpleGui
from OCC.Core.IFSelect import IFSelect_RetError
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SHELL, TopAbs_COMPOUND, TopAbs_SOLID
from OCC.Core.GeomAbs import GeomAbs_Plane
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop_LinearProperties, brepgprop_SurfaceProperties, brepgprop_VolumeProperties
from OCC.Core.TopoDS import topods

#Meshing
import gmsh
import re

#Opensees
import openseespy.opensees as ops

#Utils
import numpy as np
import math
import matplotlib.pyplot as plt
import pandas as pd
import csv
import os

EXPORT_DIR = "export/"

# Sub-paths of EXPORT_DIR, one per pipeline stage's output - imported by
# in_plane_wall.py/out_of_plane_test.py, which never got these defined here
# (import error until now). EXPORT_DIR_PART_1/2 match the directories those
# scripts' own inputs already live in on disk (export/ifc_data/'s
# CMB_unreinforced_adapted_E.json, export/mesh/'s out_of_plane.msh - both
# predate this fix, confirming the convention rather than guessing it).
# EXPORT_DIR_PART_3/LOG_DIR are imported by the same two scripts but never
# actually referenced in their bodies - defined for import-completeness only.
EXPORT_DIR_PART_1 = os.path.join(EXPORT_DIR, "ifc_data")
EXPORT_DIR_PART_2 = os.path.join(EXPORT_DIR, "mesh")
EXPORT_DIR_PART_3 = os.path.join(EXPORT_DIR, "opensees")
OUTPUT_DIR = "output/"
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")

# Geometry extraction settings
GEOMETRY_SETTINGS = ifcopenshell.geom.settings()
GEOMETRY_SETTINGS.set(GEOMETRY_SETTINGS.USE_PYTHON_OPENCASCADE, True)

# STEP Export Settings
STEP_SCHEMA = 'AP203'
STEP_ASSEMBLY_MODE = 1
STEP_UNIT = 'M'

# Initialize STEP Writer
STEP_WRITER = STEPControl_Writer()
fp = STEP_WRITER.WS().TransferWriter().FinderProcess()

# Apply Settings
Interface_Static_SetCVal('write.step.schema', STEP_SCHEMA)
Interface_Static_SetCVal('write.step.unit', STEP_UNIT)
Interface_Static_SetCVal('write.step.assembly', str(STEP_ASSEMBLY_MODE))

#Number of processors
N_PROC = ops.getNP()

#constants
# Standard gravity, m/s^2 - the "#mm/s2" this comment used to say was wrong,
# not the value: -9.810 is correct gravity in m/s^2, and every consumer of
# G (Element.create_linear_elastic_element, and, after the unit fix in
# core/opensees_generation/model_builder.py, create_plastic_damage_elements
# too) works in metres, matching STEP_UNIT='M' above and the mesh's own
# node coordinates - see model_builder.py's create_plastic_damage_elements
# docstring for the full trace of the bug this used to compound.
G = -9.810 #m/s2

#settings
SLAB_AS_SHELLS = True
