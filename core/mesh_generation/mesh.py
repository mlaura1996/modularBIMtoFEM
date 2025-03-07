from core.config import EXPORT_DIR
from core.config import gmsh, re, np
from . import connections

class GmshModel:
    @staticmethod 
    def createGmshModel(stepfile, labels, run_gmsh = True, use_adaptive_mesh = True):
        gmsh.initialize()
        gmsh.model.mesh.setOrder(2)
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add(stepfile[-4])
        gmsh.open(stepfile)
        gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
        gmsh.model.occ.synchronize()
        #gmshmodel = PhysicalGroups.add_original_material_physical_groups(gmsh.model, labels)    
        gmshmodel = PhysicalGroups.add_material_physical_groups(labels)
        gmshmodel = PhysicalGroups.add_supports_physical_groups(gmshmodel)
        gmshmodel = PhysicalGroups.add_surface_loads_physical_groups(gmshmodel)
  
        # connections.split_beam_and_assign_to_wall(gmshmodel, labels)
        # gmshmodel = PhysicalGroups.add_supports_physical_groups(gmsh.model)
        # gmsh.model.geo.removeAllDuplicates()
        # gmsh.model.removePhysicalGroups()
        # gmsh.model.occ.synchronize()
        
        # gmshmodel = PhysicalGroups.add_material_physical_groups(gmshmodel, labels)
        # #connections.extrude_beam_interface_surfaces(gmshmodel, offset=1000)
        # gmsh.model.occ.synchronize()
        #gmsh.fltk.run()

        # connections.create2DPhysicalGroups(gmshmodel)
       
        
        if use_adaptive_mesh:
            Mesh.generate_adaptive_mesh(gmshmodel, scaling_factor=1000)            
        else:
            Mesh.fast_meshing(gmshmodel, 300)
        if run_gmsh:
            gmsh.fltk.run()   

        return(gmshmodel)
        


class Mesh:

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

    @staticmethod
    def add_material_physical_groups(labels):
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
            print(f"Surface {surface} Normal: {normal}")

            # Ensure it's a **top-facing** horizontal surface
            if abs(float(normal[0])) < 0.01 and abs(float(normal[1])) < 0.01 and float(normal[2]) > 0.99:
                forLoad.append(surface)

        # Create a new Physical Group for the top surfaces (Load Application)
        if forLoad:
            gmshmodel.addPhysicalGroup(dim=2, tags=forLoad, name="Load")

        return gmsh.model
    








