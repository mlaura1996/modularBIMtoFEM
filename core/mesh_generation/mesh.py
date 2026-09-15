"""Legacy single-material meshing and physical-group tagging (gmsh).

The earlier, serial-workflow meshing path — still used by
``main.py``/``in_plane_wall.py``/``out_of_plane_test.py`` (see
:doc:`../developer_guide/architecture`), not by the interface-detection
multi-volume aggregate route in
:mod:`core.mesh_generation.wall_interfaces`.
"""

from core.config import EXPORT_DIR
from core.config import gmsh, re, np
#from . import connections

class GmshModel:
    """Builds a single gmsh model end to end: load STEP, tag materials, mesh."""

    @staticmethod
    def createGmshModel(stepfile, labels, run_gmsh = True, use_adaptive_mesh = True):
        """Load a STEP file into gmsh, fragment it, tag material physical groups, and mesh it.

        ``labels`` names the per-volume materials, consumed by
        :meth:`PhysicalGroups.add_material_physical_groups`. Meshes with
        :meth:`Mesh.generate_adaptive_mesh` by default, or
        :meth:`Mesh.fast_meshing` (fixed 0.3 m size) if
        ``use_adaptive_mesh`` is ``False``. Opens the interactive gmsh
        window (``gmsh.fltk.run()``) both mid-build and, if ``run_gmsh``,
        again after meshing. Returns the ``gmsh.model`` module itself.
        """
        gmsh.initialize()
        # Order 1 (linear Tet4), not 2: every element creator in
        # core.opensees_generation.model_builder.Element (both
        # create_linear_elastic_element and create_plastic_damage_elements)
        # unpacks node_tags directly into an OpenSees 'FourNodeTetrahedron'
        # call, which requires exactly 4 nodes per element - order 2 would
        # hand it 10-node Tet10 connectivity and fail at the element() call.
        gmsh.model.mesh.setOrder(1)
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add(stepfile[-4])
        gmsh.open(stepfile)
        gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
        gmsh.model.occ.synchronize() 
        gmshmodel = PhysicalGroups.add_material_physical_groups(labels)
        gmsh.fltk.run() 
        #gmshmodel = PhysicalGroups.add_supports_physical_groups(gmshmodel)
        #gmshmodel = PhysicalGroups.add_surface_loads_physical_groups(gmshmodel)  
        if use_adaptive_mesh:
            Mesh.generate_adaptive_mesh(gmshmodel, scaling_factor=1000)            
        else:
            Mesh.fast_meshing(gmshmodel, 0.3)
        if run_gmsh:
            gmsh.fltk.run()   

        return(gmshmodel)
        


class Mesh:
    """Mesh-generation strategies for a single-material gmsh model."""

    @staticmethod
    def fast_meshing(gmshmodel, meshSize):
        """Generate a solid mesh without refinement"""
        gmshmodel.geo.removeAllDuplicates()
        gmsh.option.setNumber("Mesh.AngleToleranceFacetOverlap", 0.001)
        gmsh.option.setNumber("Mesh.MeshSizeMax", meshSize)
        gmshmodel.mesh.generate(3)
        gmshmodel.mesh.optimize()
        gmshmodel.mesh.remove_duplicate_nodes()

        return(gmsh.model)
    

    @staticmethod
    def generate_adaptive_mesh(model, num_threads=4, scaling_factor=1, debug_file= EXPORT_DIR + "mesh_debug.log"):
        """
        Adaptive meshing ensuring at least three elements in the thickness of each solid, using parallel processing,
        with optimizations for avoiding overly small elements in regions where larger elements are acceptable.
        """
        
        gmsh.option.setNumber("General.NumThreads", num_threads)  # Enable multithreading
        model.occ.synchronize()
        volumes = model.getEntities(3)  # Extract 3D volume

        with open(debug_file, "w") as f:
            f.write("--- Mesh Debugging Log ---\n")

            for volume in volumes:
                name = model.getEntityName(volume[0], volume[1])
                if not name:
                    f.write(f"No name for volume {volume}. Skipping.\n")
                    continue

                match = re.search(r'(\d+\.\d+|\d+)_m', name)
                if match:
                    thickness = float(match.group(1)) * scaling_factor
                    f.write(f"Matched thickness: {thickness} from label: {name}\n")

                    # Ensure at least three elements in thickness
                    if thickness == 0:
                        thickness = 100
                    elif thickness > 1000:
                        thickness = thickness/5
                    elif thickness <= 0.05 and thickness > 0:
                        thickness = 0.1
                        mesh_size = thickness
                    elif thickness >= 0.2:
                        mesh_size = thickness/5                    
                    else:
                        mesh_size = thickness/3

                    # Boundary surfaces and curves
                    # Step 1: Extract boundary surfaces (dim 2) from volumes (dim 3)
                    points = gmsh.model.getBoundary([volume], oriented=False, combined=True, recursive=True)
                    print(name)
                    print(points)
                    for point in points:
                        gmsh.model.mesh.setSize([point], mesh_size)                
        gmsh.model.mesh.generate(3)
        # Save the mesh
        gmsh.write(EXPORT_DIR + "output_mesh.msh")


class PhysicalGroups():
    """Groups gmsh volumes/surfaces into named physical groups (materials, supports, loads)."""

    @staticmethod
    def add_material_physical_groups(labels):
        """Group volumes into one physical group per material name, from per-volume entity names.

        Matches each volume's gmsh entity name (set at STEP import,
        typically ``<Material>_<thickness>_m``) against the material
        prefix in ``labels`` (thickness suffix stripped), then creates one
        3D physical group per distinct material covering all matching
        volumes. Returns ``gmsh.model``.
        """
        tridEleTags = gmsh.model.occ.getEntities(dim=3)
        OriginalDictionaryKeys = []
        OriginalDictionaryValues = []
        for ele in tridEleTags:
            tg = ele[1]
            EntName = gmsh.model.getEntityName(3, tg)
            OriginalDictionaryKeys.append(EntName)
            OriginalDictionaryValues.append(tg)

        OriginalDictionary = {k: v for k, v in zip(OriginalDictionaryKeys, OriginalDictionaryValues)}
        # Extract only the material name (remove thickness)
        LabelDictionaryKeys = [x.split('_')[0] for x in labels]
        LabelDictionaryKeys = list(set(LabelDictionaryKeys))  # Remove duplicates

        LabelDictionary = {key: None for key in LabelDictionaryKeys}
        FinalDict = {}

        for key2 in LabelDictionary.keys():
            matches = [OriginalDictionary[key1] for key1 in OriginalDictionary.keys() if key2 in key1.split('_')[0]]
            if matches:
                FinalDict[key2] = matches

        for key in FinalDict.keys():
            print(key)
            print(type(key))
            value = FinalDict[key]
            print(value)
            id = gmsh.model.addPhysicalGroup(dim=3, tags=value, tag=-1, name=str(key))
            print(id)
            gmsh.model.set_physical_name(dim = 3, tag = id, name = key)
        return gmsh.model

    @staticmethod
    def add_original_material_physical_groups(gmshmodel, labels):
        """Same grouping as :meth:`add_material_physical_groups`, suffixed ``"original"``.

        Used to keep a copy of the pre-modification material grouping
        (each group named ``<material>original``) alongside a later,
        possibly-edited set of physical groups on the same model.
        """
        tridEleTags = gmshmodel.occ.getEntities(dim=3)

        OriginalDictionaryKeys = []
        OriginalDictionaryValues = []
        for ele in tridEleTags:
            tg = ele[1]
            EntName = gmshmodel.getEntityName(3, tg)
            OriginalDictionaryKeys.append(EntName)
            OriginalDictionaryValues.append(tg)

        OriginalDictionary = {k: v for k, v in zip(OriginalDictionaryKeys, OriginalDictionaryValues)}

        # Extract only the material name (remove thickness)
        LabelDictionaryKeys = [x.split('_')[0] for x in labels]
        LabelDictionaryKeys = list(set(LabelDictionaryKeys))  # Remove duplicates

        LabelDictionary = {key: None for key in LabelDictionaryKeys}
        FinalDict = {}
        for key2 in LabelDictionary.keys():
            matches = [OriginalDictionary[key1] for key1 in OriginalDictionary.keys() if key2 in key1.split('_')[0]]
            if matches:
                FinalDict[key2] = matches

        for key in FinalDict.keys():
            print(key)
            print(type(key))
            value = FinalDict[key]
            print(value)
            id = gmshmodel.addPhysicalGroup(dim=3, tags=value, tag=-1, name=key+ "original")
            print(id)
            gmsh.model.set_physical_name(dim = 3, tag = id, name = key + "original")
        return gmsh.model

    @staticmethod
    def add_supports_physical_groups(gmshmodel):
        """Tag the downward-facing boundary surfaces of the "Footing" volume group as physical group "Fix".

        Finds the volumes already grouped under the material name
        containing ``"Footing"``, takes their boundary surfaces, and keeps
        only the ones whose outward normal points straight down (the base
        surfaces that should get a support boundary condition). Returns
        ``gmsh.model``.
        """
        for dim, tag in gmshmodel.getPhysicalGroups():
            if 'Footing' in gmshmodel.getPhysicalName(dim, tag):
                footingTags = gmshmodel.getEntitiesForPhysicalGroup(3, tag)
        footingDimTag = [(3, footingTags[i]) for i in range(len(footingTags))]
        boundary = (gmshmodel.get_boundary(footingDimTag))
        boundaryTags = [sublist[1] for sublist in boundary]
        realBoundary  = [ent for ent in boundaryTags if ent < 0]
        FinalBound  = [abs(n) for n in realBoundary]

        ToFix = []
        for surface in FinalBound:
            # Get the nodes of the surface
            normal = gmshmodel.getNormal(surface, [1,0,0,1])
            if normal[2] == -1 and normal[5] ==-1:
                ToFix.append(surface)
        gmshmodel.addPhysicalGroup(dim=2, tags=ToFix, name="Fix")
        return(gmsh.model)
    
    @staticmethod
    def add_surface_loads_physical_groups(gmshmodel, runGmsh=True):
        """Tag the upward-facing boundary surfaces of the "Steel" volume group as physical group "Load".

        Mirrors :meth:`add_supports_physical_groups` but for the top
        (load-application) surfaces of the material group whose name
        contains ``"Steel"``: keeps boundary surfaces whose normal points
        essentially straight up. Returns ``gmsh.model``.
        """
        for dim, tag in gmshmodel.getPhysicalGroups():
            # Get the name of the physical group
            name = gmshmodel.getPhysicalName(dim, tag)

            # Check if it belongs to Steel
            if "Steel" in name:
                # Get volume entities (3D) inside this physical group
                BoardTags = gmshmodel.getEntitiesForPhysicalGroup(3, tag)

        # Get boundary surfaces of these 3D volumes
        BoardDimTag = [(3, BoardTags[i]) for i in range(len(BoardTags))]
        boundary = gmshmodel.getBoundary(BoardDimTag)
        boundaryTags = [sublist[1] for sublist in boundary]  # Extract surface IDs

        # Normalize the tags (remove negative signs)
        FinalBound = list(set(abs(n) for n in boundaryTags))

        # Identify the top surface using normals
        forLoad = []
        for surface in FinalBound:
            normal = gmshmodel.getNormal(surface, [0, 0, 0, 1])  # Get normal vector
            #print(f"Surface {surface} Normal: {normal}")

            # Ensure it's a **top-facing** horizontal surface
            if abs(float(normal[0])) < 0.01 and abs(float(normal[1])) < 0.01 and float(normal[2]) > 0.99:
                forLoad.append(surface)

        # Create a new Physical Group for the top surfaces (Load Application)
        if forLoad:
            gmshmodel.addPhysicalGroup(dim=2, tags=forLoad, name="Load")

        return gmsh.model
    








