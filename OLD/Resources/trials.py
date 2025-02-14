#second function
import ifcopenshell.geom
import OCC.Core.TopoDS
from OCC.Core.STEPControl import (STEPControl_AsIs, STEPControl_Writer)
from OCC.Core.Interface import Interface_Static_SetCVal
from  OCC.Core.STEPConstruct import *
from OCC.Core.TCollection import TCollection_HAsciiString
from OCC.Extend.DataExchange import read_step_file_with_names_colors
import OCC.Core.AIS
import OCC.Core.XCAFDoc
import OCC.Display.SimpleGui
from OCC.Core.IFSelect import IFSelect_RetError
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeSolid

#SEttings

#Geometry of IFC
settings = ifcopenshell.geom.settings()
settings.set(settings.USE_PYTHON_OPENCASCADE, True) #generalinfo

#StepWriter
schema = 'AP203'
assembly_mode = 1
writer = STEPControl_Writer()
fp = writer.WS().TransferWriter().FinderProcess()
Interface_Static_SetCVal('write.step.schema', schema)
Interface_Static_SetCVal('write.step.unit', 'M')
Interface_Static_SetCVal('write.step.assembly', str(assembly_mode))


def shapeCreation(element):
    if element.Representation is not None:
        try:
            product = ifcopenshell.geom.create_shape(settings, element)
        except:
            print("Shape creation failed")
        shape = OCC.Core.TopoDS.TopoDS_Iterator(product.geometry).Value()
    return shape

def getAssociatedMaterials(element):
    for rel in element.HasAssociations:
        matNameRel = rel.RelatingMaterial
        if hasattr(matNameRel, "Name") == True:
            materials = matNameRel.Name
    return materials
        
def getAssociatedMaterialFromType(element):
    elementType = element.IsTypedBy.RelatingType
    for association in elementType.HasAssociations:
        materials = association.RelatingMaterials   
    return materials

def getMaterials(materials, typeOfMaterial):
    for material in materials.typeOfMaterial:
        materialName = material.Material.Name
    return materialName

def getObjectLabel(element):
    material = getAssociatedMaterials(element)
    if material is None:
        material = getAssociatedMaterialFromType(element)
    return material
 


def STEPwriter(elements, data, fileName):

    labels = []
    for dictionary in data:
        value = dictionary['MaterialName']
        labels.append(value)

    selected_elements = []

    for element in elements:
        if element.is_a("IfcOpeningElement"):
            continue
        selected_elements.append(element)

    for element in selected_elements:
        if element.Representation is not None:
            try:
                product = ifcopenshell.geom.create_shape(settings, element)
            except:
                print("Shape creation failed")
            #product = ifcopenshell.geom.create_shape(settings, element)
            shape = OCC.Core.TopoDS.TopoDS_Iterator(product.geometry).Value()

            if int(shape.NbChildren()) > 1:
                sewing = BRepBuilderAPI_Sewing()
                face_iterator = TopExp_Explorer(shape, TopAbs_FACE)
                while face_iterator.More():
                    face = face_iterator.Current()
                    sewing.Add(face)
                    face_iterator.Next()

                sewing.Perform()
                result = sewing.SewedShape()
                print(result)
                print(face_iterator.ExploredShape())
                print('gfuyfjfgygfjy')
                solid_maker = BRepBuilderAPI_MakeSolid(result)
                print(solid_maker.Solid())
                shape = solid_maker.Solid()

            for label in labels:
                if label in str(element.ObjectType):
                    print('ok')
                    eleName = label
                    
            Interface_Static_SetCVal('write.step.product.name', eleName)
            status = writer.Transfer(shape, STEPControl_AsIs)
            if int(status) > int(IFSelect_RetError):
                raise Exception('Some Error occurred')
            item = stepconstruct.FindEntity(fp, shape)
            item.SetName(TCollection_HAsciiString(eleName))
            if not item:
                raise Exception('Item not found')

    writer.Write(fileName + '.step'), read_step_file_with_names_colors(fileName + '.step')

    return str(fileName + '.step')
