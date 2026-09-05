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
    def get_upper_surface(shape):
        """
        Dato un solido (o compound), restituisce la faccia piana superiore (massima Z),
        tra quelle con area > 0.5 * max_area.
        """
        faces = []
        ex = TopExp_Explorer(shape, TopAbs_FACE)

        while ex.More():
            face = topods.Face(ex.Current())
            surf = BRepAdaptor_Surface(face, True)

            if surf.GetType() == GeomAbs_Plane:
                props = GProp_GProps()
                brepgprop_SurfaceProperties(face, props)
                c = props.CentreOfMass()
                zc = c.Z()
                area = props.Mass()
                faces.append((face, zc, area))

            ex.Next()

        if not faces:
            return None

        max_area = max(f[2] for f in faces)
        candidate_faces = [f for f in faces if f[2] > 0.5 * max_area]
        # ordina per Z decrescente, in caso di stessa Z prende quella con area maggiore
        candidate_faces.sort(key=lambda x: (x[1], -x[2]))
        # se vuoi la più alta, la presi prima; se vuoi la seconda più alta, puoi prendere [1],
        # qui prendiamo la più alta:
        return candidate_faces[-1][0]   # faccia con Z massima

    # @staticmethod
    # def create_solid(shape):
    #     """Combines faces into a solid using BRepBuilderAPI_Sewing."""
    #     sewing = BRepBuilderAPI_Sewing()
    #     face_iterator = TopExp_Explorer(shape, TopAbs_FACE)
        
    #     while face_iterator.More():
    #         face = face_iterator.Current()
    #         sewing.Add(face)
    #         face_iterator.Next()

    #     sewing.Perform()
    #     result = sewing.SewedShape()
    #     solid_maker = BRepBuilderAPI_MakeSolid(result)
    #     return solid_maker.Solid()
    
    @staticmethod
    def create_solid(shape):
        """Combines faces into a solid using BRepBuilderAPI_Sewing."""
        sewing = BRepBuilderAPI_Sewing()
        face_iterator = TopExp_Explorer(shape, TopAbs_FACE)
        
        while face_iterator.More():
            sewing.Add(face_iterator.Current())
            face_iterator.Next()

        sewing.Perform()
        sewn = sewing.SewedShape()

        # Se il risultato è una singola shell → MakeSolid diretto
        if sewn.ShapeType() == TopAbs_SHELL:
            return BRepBuilderAPI_MakeSolid(topods.Shell(sewn)).Solid()

        # Se il risultato è un compound di shell (caso multi-solid come porte/finestre)
        # → itera le shell e costruisci un solid per ognuna, poi rimetti in un compound
        if sewn.ShapeType() == TopAbs_COMPOUND:
            compound_builder = BRep_Builder()
            result_compound = TopoDS_Compound()
            compound_builder.MakeCompound(result_compound)

            shell_iter = TopExp_Explorer(sewn, TopAbs_SHELL)
            while shell_iter.More():
                shell = topods.Shell(shell_iter.Current())
                solid = BRepBuilderAPI_MakeSolid(shell).Solid()
                compound_builder.Add(result_compound, solid)
                shell_iter.Next()

            return result_compound

        # Fallback
        return sewn

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
                if SLAB_AS_SHELLS:
                    if element.is_a("IfcSlab") or element.is_a("IfcRoof"):
                        geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)
                        slab_solid = geometry_processor.get_geom(element)
                        slab_shape = TopoDS_Iterator(slab_solid).Value()
                        shape = geometry_processor.get_upper_surface(slab_shape)
                    else:
                        geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)
                        compound = geometry_processor.get_geom(element)

                        iterator = TopoDS_Iterator(compound)
                        first_child = iterator.Value()
                        iterator.Next()
                        has_siblings = iterator.More()

                        if has_siblings:
                            # Compound con più solidi (es. porta, finestra) → unisci tutto
                            shape = GeometryProcessor.create_solid(compound)
                        elif int(first_child.NbChildren()) > 1:
                            # Figlio unico ma multi-shell → cuci in solido
                            shape = GeometryProcessor.create_solid(first_child)
                        else:
                            shape = first_child
        
                else:
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

                        iterator = TopoDS_Iterator(compound)
                        first_child = iterator.Value()
                        iterator.Next()
                        has_siblings = iterator.More()

                        if has_siblings:
                            # Compound con più solidi (es. porta, finestra) → unisci tutto
                            shape = GeometryProcessor.create_solid(compound)
                        elif int(first_child.NbChildren()) > 1:
                            # Figlio unico ma multi-shell → cuci in solido
                            shape = GeometryProcessor.create_solid(first_child)
                        else:
                            shape = first_child
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
