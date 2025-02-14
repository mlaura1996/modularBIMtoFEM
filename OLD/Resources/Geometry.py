import ifcopenshell
import ifcopenshell.geom
import OCC.Core.TopoDS
import ifcopenshell
import ifcopenshell.geom
import OCC.Core.TopoDS
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib_Add
from OCC.Core.TopoDS import TopoDS_Compound, TopoDS_Shape, TopoDS_Iterator
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
from OCC.Display.SimpleGui import init_display
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
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib_Add

#Settings

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

def getObjectLabel(element, element_dictionary):
    tag = element_dictionary.get(element, "NoTag")  # Get the tag from the dictionary, default to "NoTag"
    if element.is_a("IfcFooting"):
        tag = "Footing" + tag
    return tag

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

def get_lowest_solid(compound):
    iterator = TopoDS_Iterator(compound)
    lowest_solid = None
    min_z = float('inf')

    # Iterate over solids in the compound
    while iterator.More():
        shape = iterator.Value()
        iterator.Next()

        # Get bounding box
        bbox = Bnd_Box()
        brepbndlib_Add(shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

        # Compare to find the lowest solid
        if zmin < min_z:
            min_z = zmin
            lowest_solid = shape

    return lowest_solid


def exportShape(element):
    shape = None  # Initialize shape to None to avoid UnboundLocalError
    

    if element.Representation is not None:
        try:
            if element.is_a("IfcSlab"):
                product = ifcopenshell.geom.create_shape(settings, element)
                compound = product.geometry  # TopoDS_Compound

                # Extract the lowest solid
                if compound.ShapeType() == OCC.Core.TopAbs.TopAbs_COMPOUND:
                    shape = get_lowest_solid(compound)
                else:
                    shape = OCC.Core.TopoDS.TopoDS_Iterator(product.geometry).Value()
            else:                
                product = ifcopenshell.geom.create_shape(settings, element)
                shape = OCC.Core.TopoDS.TopoDS_Iterator(product.geometry).Value()

                if int(shape.NbChildren()) > 1:
                    shape = createSolid(shape)
        except Exception as e:
            print(f"Element {element.Name} has no representation or failed to export: {e}")

    return shape



def createSpecialSTEPFile(elements, element_dict, fileName):
    labels = []
    for element in elements:
        shape = exportShape(element)
        print(element)
        print(shape)
        
        if shape is None:
            print(f"Skipping element {element.Name} due to missing geometry.")
            continue  # Skip if no shape
        
        label = getObjectLabel(element, element_dict)
        labels.append(label)

        Interface_Static_SetCVal('write.step.product.name', label)
        status = writer.Transfer(shape, STEPControl_AsIs)
        if int(status) > int(IFSelect_RetError):
            raise Exception('Some Error occurred')
        item = stepconstruct_FindEntity(fp, shape)
        item.SetName(TCollection_HAsciiString(label))
        if not item:
            raise Exception('Item not found')

    
    writer.Write(fileName + '.step'), read_step_file_with_names_colors(fileName + '.step')
    return (str(fileName + '.step')), (labels)
