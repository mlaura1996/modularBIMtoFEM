import ifcopenshell
import ifcopenshell.geom
import OCC.Core.TopoDS
from OCC.Core.STEPControl import (STEPControl_AsIs, STEPControl_Writer)
from OCC.Core.Interface import Interface_Static
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
Interface_Static.SetCVal('write.step.schema', schema)
Interface_Static.SetCVal('write.step.unit', 'M')
Interface_Static.SetCVal('write.step.assembly', str(assembly_mode))

def exportAlphanumericalProperties(ifcfile):

    ifc_file = ifcopenshell.open(ifcfile)
    materials = ifc_file.by_type('IfcMaterial')
    materialsProperties = []

    for material in materials:
        materialsProperties.append(getMaterialProperties(material))

    return materialsProperties

        
def getMaterialProperties(ifcMaterial):
        PropertiesName =  []
        PropertiesValue = []
        PropertiesName.append('MaterialName')
        label = str(ifcMaterial.Name)
        PropertiesValue.append(label) #this is to create physical groups 
        for pset in ifcMaterial.HasProperties:
            if pset.Name == "Pset_MaterialCommon" or pset.Name == "Pset_MaterialMechanical":                     
                property = [item for item in pset if isinstance(item, tuple)] #the properties are stored as tuples
                for ele in property[0]:
                    PropertiesName.append(ele[0])
                    PropertiesValue.append(ele[2][0])

        return {PropertiesName[i]: PropertiesValue[i] for i in range(len(PropertiesName))}


def cleanDictionary(dictionary):
    cleanDictionary = []
    for item in dictionary:
        if item not in cleanDictionary:
            cleanDictionary.append(item)
    return cleanDictionary


"""Geometry"""
def getObjectLabel(element): 
    label = getAssociatedMaterialsFromInstance(element)
    if element.is_a("IfcFooting"):
        label = "Footing" + label
    return label


def getAssociatedMaterialsFromInstance(element):
    for rel in element.HasAssociations:
        matNameRel = rel.RelatingMaterial
        if hasattr(matNameRel, "Name") == True:
            material = matNameRel.Name
        elif rel.RelatingMaterial.is_a()=="IfcMaterialLayerSet": #because of Roofs
            for matlayer in rel.RelatingMaterial.MaterialLayers:
                material = matlayer.Material.Name
        elif rel.RelatingMaterial.is_a()=="IfcMaterialProfileSet": #because of Beams/columns
            for matlayer in rel.RelatingMaterial.MaterialLayers:
                material = matlayer.Material.Name
        else:
            material = getAssociatedMaterialFromType(element)
    return material

        
def getAssociatedMaterialFromType(element):
    for Type in element.IsTypedBy:
        ElementType = Type.RelatingType
        for relType in ElementType.HasAssociations:
            if relType.RelatingMaterial.is_a()=="IfcMaterialLayerSet": #because of Walls
                #print('Material is attributed to type and it is based on a layer: ' + str(ElementType[2]) )
                for matlayer in relType.RelatingMaterial.MaterialLayers:
                    material = matlayer.Material.Name
            elif relType.RelatingMaterial.is_a()=="IfcMaterialProfileSet": #because of beams    
                #print('Material is attributed to type and it is based on profiles')
                for relass in relType.RelatingMaterial.MaterialProfiles:
                    material = relass.Material.Name
            else:
                material = relType.RelatingMaterial                       
    return material

def createSolid(shape):
    sewing = BRepBuilderAPI_Sewing()
    face_iterator = TopExp_Explorer(shape, TopAbs_FACE)
    while face_iterator.More():
        face = face_iterator.Current()
        sewing.Add(face)
        face_iterator.Next()
    sewing.Perform()
    result = sewing.SewedShape()
    solid_maker = BRepBuilderAPI_MakeSolid(result)
    shape = solid_maker.Solid()
    
    return shape

def exportShape(element):
    if element.Representation is not None:
            try:
                product = ifcopenshell.geom.create_shape(settings, element)
            except:
                print("Element has no representation!")
            shape = OCC.Core.TopoDS.TopoDS_Iterator(product.geometry).Value()

            if int(shape.NbChildren()) > 1:
                shape = createSolid(shape)             
    return shape
                

def createSpecialSTEPFile(elements, fileName):
    labels = []
    for element in elements:
        shape = exportShape(element)
        label = getObjectLabel(element)
        labels.append(label)

        Interface_Static.SetCVal('write.step.product.name', label)
        status = writer.Transfer(shape, STEPControl_AsIs)
        if int(status) > int(IFSelect_RetError):
            raise Exception('Some Error occurred')
        item = stepconstruct.FindEntity(fp, shape)
        item.SetName(TCollection_HAsciiString(label))
        if not item:
            raise Exception('Item not found')
    writer.Write(fileName + '.step'), read_step_file_with_names_colors(fileName + '.step')
    return (str(fileName + '.step')), (labels)




