import Resources
import ifcopenshell
#import gmsh2opensees as g2o


from Resources.OpenseesModelBuilder import ModelBuilder as ModelBuilder
from Resources.OpenseesModelBuilder import Element as Element
from Resources.OpenseesModelBuilder import Loads as Loads
from Resources.OpenseesModelBuilder import BoundaryConditions as BoundaryConditions
from Resources.StaticAnalysis import monotonicPushoverAnalysis as Pushover 
from Resources.StaticAnalysis import utils as utils
from Resources.Visualisation import visualizePointsOfInterest as point

Properties = Resources.Input.exportAlphanumericalProperties('./Models/TestWall.ifc')


ifc_file = ifcopenshell.open('./Models/TestWall.ifc')
elements = ifc_file.by_type('IfcBuildingElement')

file, labels = Resources.Input.createSpecialSTEPFile(elements, "File")
gmshMod = Resources.Mesh.createGmshModel(file, labels, False)

builder = ModelBuilder(ndm = 3,ndf = 3)
builder.initialize_model()

#element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

#Element.create_plastic_damage_elements(gmshMod, Properties, 1)

elementTags = (Element.add_elements_to_opensees(Element, gmshMod, Properties))

controlpoint = utils.getNodeWithHigherCoords(gmshMod)
print(utils.getBaseNode(gmshMod))

basePoint = utils.getBaseNode(gmshMod)

#point.highlight_control_point(gmshMod, controlpoint)

Loads("Linear", 1, "Plain", 1)

SW = Loads.addSelfWeight(elementTags)

# # print(len(elementTags))

# SW.addSelfWeight(elementTags)

BoundaryConditions.fixNodes(gmshMod)

Pushover.PushoverLcf(10, controlpoint, basePoint, elementTags, gmshMod)

# Pushover.PushoverDcf(1, 0.1, gmshMod)

#print(Properties)




