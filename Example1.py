import Resources
import ifcopenshell


import Resources.StructuralModel

Properties = Resources.Input.exportAlphanumericalProperties('./Models/TestWall.ifc')


ifc_file = ifcopenshell.open('./Models/TestWall.ifc')
elements = ifc_file.by_type('IfcBuildingElement')

file, labels = Resources.Input.createSpecialSTEPFile(elements, "File")
gmshMod = Resources.Mesh.createGmshModel(file, labels)

print(Properties)

#Resources.StructuralModel()