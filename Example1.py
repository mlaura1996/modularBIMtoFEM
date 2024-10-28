import Resources
import ifcopenshell
#import gmsh2opensees as g2o
import gmsh
import sys

from Resources.OpenseesModelBuilder import Model as model
from Resources.StaticAnalysis import utils as utils
from Resources.Visualisation import postProcessing as ps



Properties = Resources.Input.exportAlphanumericalProperties('./Models/TestWall.ifc')
print(Properties)


ifc_file = ifcopenshell.open('./Models/TestWall.ifc')
elements = ifc_file.by_type('IfcBuildingElement')

file, labels = Resources.Input.createSpecialSTEPFile(elements, "File")
gmshMod = Resources.Mesh.createGmshModel(file, labels, False)



model.create_solid_model(gmshMod, Properties)


# ps.create_csv_file_for_force_displacement_recorder("GravityLoads_20241028_092158/gravity_reactions.out", "GravityLoads_20241028_092158/gravity_displacement.out", "SW.csv")
# ps.plot_reaction_vs_displacement("SW.csv")

# gmsh.initialize()
# gmsh.open("GravityLoads_20241028_092158/SW_Displacement.pos")
# gmsh.open("GravityLoads_20241028_092158/SW_Reactions.pos")
#gmsh.fltk.run()



