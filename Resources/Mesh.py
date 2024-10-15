import gmsh
import openseespy.opensees as ops

np = ops.getNP()

def createGmshModel(stepfile, labels, runGmsh = True):
    gmsh.initialize()
    gmsh.model.mesh.setOrder(2)
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add(stepfile[-4])
    gmsh.open(stepfile)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    gmshmodel = createMatPhisicalGroups(gmsh.model, labels)

    gmshmodel = fixBoundaries(gmsh.model)
    # # for load in loads:
    # #     gmshmodel = applyLoad(gmshmodel, load)
    gmshmodel = meshing(gmshmodel, 200, False) #needs to be external
    # gmshmodel = paralleliseMesh(gmshmodel)
    # partitions = getElementInPartitions(gmshmodel)         
    # print(len(partitions))
    if runGmsh:
        gmsh.fltk.run()
    return(gmsh.model)


def createMatPhisicalGroups(gmshmodel, labels):
    tridEleTags = gmshmodel.occ.getEntities(dim = 3)

    OriginalDictionaryKeys = []
    OriginalDictionaryValues = []
    for ele in tridEleTags:
        tg = ele[1]
        EntName = gmshmodel.getEntityName(3, tg)
        OriginalDictionaryKeys.append(EntName)
        OriginalDictionaryValues.append(tg)

    OriginalDictionary= {k: v for k, v in zip(OriginalDictionaryKeys, OriginalDictionaryValues)}

    LabelDictionaryKeys = []
    [LabelDictionaryKeys.append(x) for x in labels if x not in LabelDictionaryKeys]
    LabelDictionaryValues = [0]*len(LabelDictionaryKeys)

    LabelDictionary = {key: None for key in LabelDictionaryKeys}

    FinalDict = {}

    for key2 in LabelDictionary.keys():
        matches = [OriginalDictionary[key1] for key1 in OriginalDictionary.keys() if key2 in key1]
        if matches:
            FinalDict[key2] = matches


    for key in FinalDict.keys():
        value = FinalDict[key]
        gmshmodel.addPhysicalGroup(dim=3, tags=value, name=key)
    return(gmsh.model)
   
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

def meshing(gmshmodel, meshSize, runGmsh = True): #attenzione che voglio fare un parametro ifc
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



