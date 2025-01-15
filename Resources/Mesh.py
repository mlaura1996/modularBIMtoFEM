import gmsh
import openseespy.opensees as ops
import re
import os

np = ops.getNP()

def createGmshModel(stepfile, labels):
    gmsh.initialize()
    gmsh.model.mesh.setOrder(2)
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add(stepfile[-4])
    gmsh.open(stepfile)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    gmshmodel = createMatPhisicalGroups(gmsh.model, labels)
    gmshmodel = fixBoundaries(gmsh.model)
    mesh_size(gmshmodel)
    #adaptive_mesh_(gmshmodel)
    #gmsh.model.geo.synchronize()
    #gmsh.write("example_model.geo")
    #smart_mesh_model(gmshmodel)
    
    # # for load in loads:
    # #     gmshmodel = applyLoad(gmshmodel, load)
    
    #gmshmodel = meshing(gmshmodel, 20, True) #needs to be external
    # gmshmodel = paralleliseMesh(gmshmodel)
    # partitions = getElementInPartitions(gmshmodel)         
    # print(len(partitions))

# def get_mesh_size(thickness, scaling_factor):
#     if thickness <= 0.05:
#         return 0.01
#     return thickness * scaling_factor



import gmsh
import re
def mesh_size(
    model,
    num_threads=4,
    scaling_factor=1,
    global_max_mesh=10,
    global_min_mesh=0.5,
    debug_file="mesh_debug.log"
):
    """
    Adaptive meshing ensuring at least three elements in the thickness of each solid, using parallel processing,
    with optimizations for avoiding overly small elements in regions where larger elements are acceptable.
    """
    
    # gmsh.option.setNumber("General.NumThreads", num_threads)  # Enable multithreading
    # gmsh.option.setNumber("Mesh.Algorithm3D", 4)  # Use Frontal-Delaunay for balanced meshing
    # gmsh.option.setNumber("Mesh.Optimize", 1)  # Enable mesh optimization
    # gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)  # Use Netgen optimization for quality
    # gmsh.option.setNumber("Mesh.MeshSizeMax", global_max_mesh)  # Set global max mesh size
    # gmsh.option.setNumber("Mesh.MeshSizeMin", global_min_mesh)  # Set global min mesh size

    model.occ.synchronize()
    volumes = model.getEntities(3)  # Extract 3D volumes

    fields = []
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
                if thickness <= 0.05:
                    thickness = 0.1
                    mesh_size = thickness

                elif thickness >= 0.2:
                    mesh_size = thickness/3
                
                else:
                    mesh_size = thickness/2


                # Boundary surfaces and curves
                # Step 1: Extract boundary surfaces (dim 2) from volumes (dim 3)
                points = gmsh.model.getBoundary([volume], oriented=False, combined=True, recursive=True)
                print(name)
                print(points)
                for point in points:
                    gmsh.model.mesh.setSize([point], mesh_size)
            
    gmsh.model.mesh.generate(3)

    # Save the mesh
    gmsh.write("output_mesh.msh")
    gmsh.fltk.run();
    # Finalize
    gmsh.finalize()


def adaptive_mesh_(
    model,
    num_threads=4,
    scaling_factor=1,
    global_max_mesh=10,
    global_min_mesh=0.5,
    debug_file="mesh_debug.log"
):
    """
    Adaptive meshing ensuring at least three elements in the thickness of each solid, using parallel processing,
    with optimizations for avoiding overly small elements in regions where larger elements are acceptable.
    """
    
    gmsh.option.setNumber("General.NumThreads", num_threads)  # Enable multithreading
    gmsh.option.setNumber("Mesh.Algorithm3D", 4)  # Use Frontal-Delaunay for balanced meshing
    gmsh.option.setNumber("Mesh.Optimize", 1)  # Enable mesh optimization
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)  # Use Netgen optimization for quality
    gmsh.option.setNumber("Mesh.MeshSizeMax", global_max_mesh)  # Set global max mesh size
    gmsh.option.setNumber("Mesh.MeshSizeMin", global_min_mesh)  # Set global min mesh size

    model.occ.synchronize()
    volumes = model.getEntities(3)  # Extract 3D volumes

    fields = []
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
                if thickness <= 0.05:
                    thickness = 0.05
                mesh_size = thickness / 3


                # Boundary surfaces and curves
                # Step 1: Extract boundary surfaces (dim 2) from volumes (dim 3)
                surfaces = gmsh.model.getBoundary([volume], oriented=False, combined=True, recursive=False)
                surface_tags = [s[1] for s in surfaces if s[0] == 2]

                # Step 2: Extract boundary curves (dim 1) from surfaces
                curve_tags = []
                for surface in surface_tags:
                    curves = gmsh.model.getBoundary([(2, surface)], oriented=False, combined=True, recursive=False)
                    for c in curves:
                        if c[0] == 1:  # Extract only curves (dim=1)
                            curve_tags.append(c[1])
                            print(f"Found curve {c[1]} for surface {surface}")

                field = gmsh.model.mesh.field.add("AttractorAnisoCurve")
                gmsh.model.mesh.field.setNumbers(field, "CurvesList", curve_tags)
                gmsh.model.mesh.field.setNumber(field, "Sampling", 40)

                # Set field parameters
                # gmsh.model.mesh.field.setNumber(field, "SizeMinNormal", mesh_size/3)
                # gmsh.model.mesh.field.setNumber(field, "SizeMaxNormal", mesh_size)
                gmsh.model.mesh.field.setNumber(field, "DistMin", mesh_size/2)
                gmsh.model.mesh.field.setNumber(field, "DistMax", mesh_size)

                fields.append(field)
                f.write(f"Field {field} created with mesh size {mesh_size}\n")
            else:
                f.write(f"No match for volume name: {name}\n")

        if fields:
            # Combine fields using the Min field
            combine_field = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(combine_field, "FieldsList", fields)
            gmsh.model.mesh.field.setAsBackgroundMesh(combine_field)
            f.write(f"Set background mesh field with fields: {fields}\n")
        else:
            f.write("No fields created. Mesh will not be adapted.\n")

        # Save the background field for debugging
        gmsh.write("background_field.pos")

    try:
        # Generate the mesh with parallel processing
        model.mesh.generate(3)
        gmsh.write("adaptive_mesh_optimized.msh")
        print("Mesh generation complete with parallel processing and optimizations.")
    except Exception as e:
        print(f"Error during meshing: {e}")
        gmsh.write("partial_mesh_error.msh")
    gmsh.fltk.run(); 


    gmsh.finalize()


def get_mesh_size(thickness):
    if thickness <= 0.1:
        thickness = 0.1
    return thickness

def adaptive_mesh_by_thickness(model, scaling_factor=2, global_max_mesh=5, debug_file="mesh_debug.log"):
    """
    Apply adaptive anisotropic mesh refinement based on the thickness stored in entity names.
    
    Parameters:
        model (gmsh.model): The Gmsh model object to apply meshing to.
        scaling_factor (float): Factor to scale the mesh size relative to thickness.
        global_max_mesh (float): Global maximum mesh size to enforce.
        debug_file (str): File to store debugging information.
        timeout (int): Maximum time allowed for meshing (in seconds).
    """


    model.occ.synchronize()
    volumes = model.getEntities(3)  # Extract 3D volumes



    fields = []
    with open(debug_file, "w") as f:
        f.write("--- Mesh Debugging Log ---\n")

        for volume in volumes:
            name = model.getEntityName(volume[0], volume[1])
            match = re.search(r'(\d+\.\d+|\d+)_m', name)

            if match:
                thickness = float(match.group(1))
                #thickness = thickness*10
                f.write(f"Matched thickness: {thickness} from label: {name}\n")

                # Step 1: Extract boundary surfaces (dim 2) from volumes (dim 3)
                surfaces = gmsh.model.getBoundary([volume], oriented=False, combined=True, recursive=False)
                surface_tags = [s[1] for s in surfaces if s[0] == 2]

                # Step 2: Extract boundary curves (dim 1) from surfaces
                curve_tags = []
                for surface in surface_tags:
                    curves = gmsh.model.getBoundary([(2, surface)], oriented=False, combined=True, recursive=False)
                    for c in curves:
                        if c[0] == 1:  # Extract only curves (dim=1)
                            curve_tags.append(c[1])
                            print(f"Found curve {c[1]} for surface {surface}")

                if not curve_tags:
                    f.write(f"No curves found for volume {volume}. Skipping.\n")
                    continue

                field = gmsh.model.mesh.field.add("AttractorAnisoCurve")
                gmsh.model.mesh.field.setNumbers(field, "CurvesList", curve_tags)
                gmsh.model.mesh.field.setNumber(field, "Sampling", 10)  # Reduce sampling to avoid over-refinement

                mesh_size = get_mesh_size(thickness)
                mesh_size = mesh_size/scaling_factor

                gmsh.model.mesh.field.setNumber(field, "SizeMinNormal", mesh_size)
                gmsh.model.mesh.field.setNumber(field, "SizeMaxNormal", thickness)
                gmsh.model.mesh.field.setNumber(field, "SizeMinTangent", mesh_size)
                gmsh.model.mesh.field.setNumber(field, "SizeMaxTangent", thickness)
                gmsh.model.mesh.field.setNumber(field, "DistMin", thickness * 0.3)
                gmsh.model.mesh.field.setNumber(field, "DistMax", thickness * 1.0)

                f.write(f"Field {field} created with SizeMinNormal = {mesh_size}\n")
                fields.append(field)
            else:
                f.write(f"No match found for label: {name}\n")

        if fields:
            combine_field = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(combine_field, "FieldsList", fields)
            gmsh.model.mesh.field.setAsBackgroundMesh(combine_field)
            f.write(f"Background mesh field set using fields: {fields}\n")
        else:
            f.write("No fields created. Mesh will not be adapted.\n")

        gmsh.option.setNumber("Mesh.MeshSizeMax", global_max_mesh)
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0.1)

        f.write(f"MeshSizeMax: {gmsh.option.getNumber('Mesh.MeshSizeMax')}\n")
        f.write(f"MeshSizeMin: {gmsh.option.getNumber('Mesh.MeshSizeMin')}\n")
        bbox = gmsh.model.getBoundingBox(3, 1)
        f.write(f"Bounding box: {bbox}\n")

        gmsh.write("background_field.pos")
        f.write("Background field exported to background_field.pos\n")

    try:
        model.mesh.generate(3)
        gmsh.write("adaptive_mesh.msh")
        print("Mesh generation complete with adaptive refinement.")
    except Exception as e:
        print(f"Error during meshing: {e}")
        gmsh.write("partial_mesh_error.msh")

    gmsh.fltk.run()
    gmsh.finalize()



def createMatPhisicalGroups(gmshmodel, labels):
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
    LabelDictionaryValues = [0] * len(LabelDictionaryKeys)

    LabelDictionary = {key: None for key in LabelDictionaryKeys}
    FinalDict = {}

    for key2 in LabelDictionary.keys():
        matches = [OriginalDictionary[key1] for key1 in OriginalDictionary.keys() if key2 in key1.split('_')[0]]
        if matches:
            FinalDict[key2] = matches

    for key in FinalDict.keys():
        value = FinalDict[key]
        gmshmodel.addPhysicalGroup(dim=3, tags=value, name=key)
    return gmsh.model

   
def fixBoundaries(gmshmodel):
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



def applyLoad(gmshmodel, runGmsh = True, name=""): #in the BIM model I have to define the various types of load and then names 
    for dim, tag in gmshmodel.getPhysicalGroups():
    # get the name of the physical group
        name = gmshmodel.getPhysicalName(dim, tag)

    # check if the name is "Fix"
    if "Loaded" in name:
        # get the tags of all the entities in the physical group "Fix"
        BoardTags = gmshmodel.getEntitiesForPhysicalGroup(3, tag)

    BoardDimTag = [(3, BoardTags[i]) for i in range(len(BoardTags))]
    boundary = (gmshmodel.get_boundary(BoardDimTag))
    boundaryTags = [sublist[1] for sublist in boundary]
    realBoundary  = [ent for ent in boundaryTags if ent < 0]
    FinalBound  = [abs(n) for n in boundaryTags]

    # Compute the normal of each surface
    
    forLoad = []
    for surface in FinalBound:
        normal = gmshmodel.getNormal(surface, [1,0,0,1])
        print(str(surface) + str(normal))
        if float(normal[2]) > 0 and float(normal[5]) > 0:
            forLoad.append(surface)

    gmshmodel.addPhysicalGroup(dim=2, tags=forLoad, name=name)

    return(gmsh.model)

def meshing(gmshmodel, meshSize, runGmsh = True): 
    gmshmodel.geo.removeAllDuplicates()

    gmsh.option.setNumber("Mesh.AngleToleranceFacetOverlap", 0.001)
    gmsh.option.setNumber("Mesh.MeshSizeMax", meshSize)

    gmshmodel.mesh.generate(3)
    gmshmodel.mesh.optimize()
    gmshmodel.mesh.remove_duplicate_nodes()

    if runGmsh:
        gmsh.fltk.run()

    return(gmsh.model)

def paralleliseMesh(gmshmodel, partitioner=0, write_to_disk=1):

    # Set options directly using function arguments
    gmsh.option.setNumber("Mesh.PartitionCreateTopology", 1)
    gmsh.option.setNumber("Mesh.PartitionCreateGhostCells", 0)
    gmsh.option.setNumber("Mesh.PartitionCreatePhysicals", 0)
    gmsh.option.setNumber("Mesh.PartitionOldStyleMsh2", 0)
    gmsh.option.setNumber("Mesh.PartitionSplitMeshFiles", 0)

    if partitioner == 0:
        # Use Metis to create partitions
        gmshmodel.mesh.partition(np)
    else:
        gmsh.plugin.setNumber("SimplePartition", "NumSlicesX", np)
        gmsh.plugin.setNumber("SimplePartition", "NumSlicesY", 1)
        gmsh.plugin.setNumber("SimplePartition", "NumSlicesZ", 1)
        gmsh.plugin.run("SimplePartition")

    # Save mesh file (or files, if `Mesh.PartitionSplitMeshFiles' is set):
    if write_to_disk == 1:
        gmsh.write("partitionedModel.msh")

    return(gmsh.model)

def getElementInPartitions(gmshmodel):

    partition_groups = {}

    entities = gmshmodel.getEntities()
    for e in entities:
        partitions = gmshmodel.getPartitions(e[0], e[1])
        if len(partitions):
            for partition in partitions:
                if partition not in partition_groups:
                    partition_groups[partition] = []
                partition_groups[partition].append(e)
    gmsh.fltk.run()
    return(partition_groups)



