import openseespy.opensees as ops
from .gmsh2opensees import * 
from .Materials import *

def GenerateOpenseesModel(gmshmodel, data):
    #modelBuilder
    ops.model("basicBuilder","-ndm",3,"-ndf",3)
    
    dim = -1  
    tag = -1
    nodeTags, coords, parametricCoord = gmshmodel.mesh.getNodes(dim, tag)

    elementTags = []

    add_nodes_to_ops(nodeTags, gmshmodel, remove_duplicates=True)

    #solid material tag
    tags = []

    for dictionary in data:

        #Get all the tags that will be in OpenSees - needed to show the results in Gmsh
        PhysicalGroup = dictionary['MaterialName']

        elementTags, nodeTags, elementName, elementNnodes = get_elements_and_nodes_in_physical_group(PhysicalGroup, gmshmodel)
        elementTags.append(elementTags)
        
        #Create the material
        solidMaterialTag = addUniqueSolidMaterialTags(tags)

        #Define Material Type
        if dictionary['MaterialModelType'] == 'LinearElastic':
            tag = CreateLinearElasticModel(gmshmodel, dictionary, solidMaterialTag)                      
        if dictionary['MaterialModelType'] == 'PlasticDamage':
            tag = CreatePlasticDamageModel(gmshmodel, dictionary, solidMaterialTag)  
        tags.append(tag)          
    print('Tags:', tags)
        
    #Create boundary conditions
    elementTags2, nodeTags2, elementName2, elementNnodes2 = get_elements_and_nodes_in_physical_group("Fix", gmshmodel)
    fix_nodes(nodeTags2, 'XYZ')


    
    return ops, elementTags, nodeTags