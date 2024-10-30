import Resources
import ifcopenshell
#import gmsh2opensees as g2o
import gmsh
import sys

from Resources.OpenseesModelBuilder import Model as model
from Resources.StaticAnalysis import utils as utils
from Resources.Visualisation import postProcessing as ps



# Properties = Resources.Input.exportAlphanumericalProperties('./Models/TestWall.ifc')
# print(Properties)


# ifc_file = ifcopenshell.open('./Models/TestWall.ifc')
# elements = ifc_file.by_type('IfcBuildingElement')

# file, labels = Resources.Input.createSpecialSTEPFile(elements, "File")
# gmshMod = Resources.Mesh.createGmshModel(file, labels, False)



# model.create_solid_model(gmshMod, Properties)


ps.create_csv_file_for_force_displacement_recorder("HLoads_20241029_150253/Horizonal_reactions.out", "HLoads_20241029_150253/Horizonal_displacement.out", "HR.csv")
ps.plot_reaction_vs_displacement("HR.csv")

# gmsh.initialize()
# gmsh.open("HLoads_20241029_150253/SW_Displacement.pos")
# gmsh.open("HLoads_20241029_150253/SW_Reactions.pos")
gmsh.fltk.run()



