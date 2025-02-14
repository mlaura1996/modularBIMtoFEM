from core.config import *


class GeometryProcessor:
    """Handles geometry extraction and processing from IFC elements."""
    
    def __init__(self, settings):
        self.settings = settings

    def get_geom(self, element):
        """Extracts the TopoDS_Compound geometry from an IFC element."""
        product = ifcopenshell.geom.create_shape(self.settings, element)
        return product.geometry  # TopoDS_Compound
    
    @staticmethod
    def get_lowest_solid(compound):
        """Finds the lowest solid in a compound (based on Z coordinate)."""
        iterator = TopoDS_Iterator(compound)
        lowest_solid = None
        min_z = float('inf')

        while iterator.More():
            shape = iterator.Value()
            iterator.Next()

            bbox = Bnd_Box()
            brepbndlib_Add(shape, bbox)
            xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

            if zmin < min_z:
                min_z = zmin
                lowest_solid = shape

        return lowest_solid

    @staticmethod
    def create_solid(shape):
        """Combines faces into a solid using BRepBuilderAPI_Sewing."""
        sewing = BRepBuilderAPI_Sewing()
        face_iterator = TopExp_Explorer(shape, TopAbs_FACE)
        
        while face_iterator.More():
            face = face_iterator.Current()
            sewing.Add(face)
            face_iterator.Next()

        sewing.Perform()
        result = sewing.SewedShape()
        solid_maker = BRepBuilderAPI_MakeSolid(result)
        return solid_maker.Solid()

class ObjectLabeler:
    """Handles generating labels for IFC elements."""
    
    @staticmethod
    def get_object_label(element, element_dict):
        """Assigns a label to an IFC element."""
        tag = element_dict.get(element, "NoTag")
        if element.is_a("IfcFooting"):
            tag = "Footing" + tag
        return tag

class StepExporter:
    """Handles exporting IFC geometry to STEP files."""
    
    def __init__(self, writer):
        self.writer = writer  # STEP_WRITER
        self.fp = writer.WS().TransferWriter().FinderProcess()

    @staticmethod
    def export_shape(geometry_processor, element):
        """Processes an IFC element and extracts its shape for export."""
        shape = None

        if element.Representation is not None:
            try:
                if element.is_a("IfcSlab"):
                    geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)
                    compound = geometry_processor.get_geom(element)

                    if compound.ShapeType() == OCC.Core.TopAbs.TopAbs_COMPOUND:
                        shape = GeometryProcessor.get_lowest_solid(compound)
                    else:
                        shape = TopoDS_Iterator(compound).Value()
                else:
                    geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)
                    compound = geometry_processor.get_geom(element)
                    shape = TopoDS_Iterator(compound).Value()

                    if int(shape.NbChildren()) > 1:
                        shape = GeometryProcessor.create_solid(shape)
            except Exception as e:
                print(f"Element {element.Name} failed to export: {e}")
        return shape

    def generate_step_file(self, elements, element_dict, filename):
        """Creates a STEP file from a list of IFC elements."""
        labels = []
        geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)

        for element in elements:
            shape = self.export_shape(geometry_processor, element)
            if shape is None:
                print(f"Skipping {element.Name} due to missing geometry.")
                continue

            label = ObjectLabeler.get_object_label(element, element_dict)
            labels.append(label)

            Interface_Static_SetCVal('write.step.product.name', label)
            status = self.writer.Transfer(shape, STEPControl_AsIs)
            if int(status) > int(IFSelect_RetError):
                raise Exception('Error during STEP export')

            item = stepconstruct_FindEntity(self.fp, shape)
            item.SetName(TCollection_HAsciiString(label))
            if not item:
                raise Exception('Item not found')

        self.writer.Write(f"{filename}.step")
        read_step_file_with_names_colors(f"{filename}.step")

        return f"{filename}.step", labels
