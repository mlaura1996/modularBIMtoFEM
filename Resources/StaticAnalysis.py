import openseespy.opensees as ops
import gmsh
import numpy as np
from .gmsh2opensees import * 
from .Visualisation import * 

class utils:
    
    @staticmethod
    def LcBasicAnalysisLoop(ok, nn):

        """Create an analysis loop to improve convergency"""
        if ok !=0:
            print("Trying 10 times smaller timestep at load factor", nn)
            ops.integrator("LoadControl", .1)
            ok = ops.analyze(1)        

        if ok !=0:
            print("Trying 100 times smaller timestep at load factor", nn) #100 smaller is already ok
            ops.integrator("LoadControl", .01)
            ok = ops.analyze(1)        
        
        if ok !=0:
            print("Trying 200 iterations at load factor", nn)
            ops.integrator("LoadControl", .01)
            ops.test("NormDispIncr", 1.*10**-11, 200)
            ok = ops.analyze(1)

        
        if ok !=0:
            print("Trying Modified Newton algorithm at load factor", nn)
            ops.algorithm("ModifiedNewton")
            ok = ops.analyze(1)

        return ok
    
    def DcBasicAnalysisLoop(ok, node_tag, dof, disp_increment, nn):
        """Create an analysis loop to improve convergence for Displacement Control"""
        if ok != 0:
            print("Trying 10 times smaller displacement increment at step", nn)
            ops.integrator("DisplacementControl", node_tag, dof, disp_increment * 0.1)
            ok = ops.analyze(1)

        if ok != 0:
            print("Trying 100 times smaller displacement increment at step", nn)
            ops.integrator("DisplacementControl", node_tag, dof, disp_increment * 0.01)
            ok = ops.analyze(1)

        if ok != 0:
            print("Trying 200 iterations at step", nn)
            ops.integrator("DisplacementControl", node_tag, dof, disp_increment * 0.01)
            ops.test("NormDispIncr", 1.*10**-11, 200)
            ok = ops.analyze(1)

        if ok != 0:
            print("Trying Modified Newton algorithm at step", nn)
            ops.algorithm("ModifiedNewton")
            ok = ops.analyze(1)

        return ok
    
    @staticmethod
    def getNodeWithHigherCoords(gmshmodel):
        node_tags, node_coords, _ = gmshmodel.mesh.getNodes()
        node_coords = np.array(node_coords).reshape(-1, 3)

        max_z_index = np.argmax(node_coords[:, 2])  # Index of the node with the highest Z value
        max_z_value = node_coords[max_z_index, 2]  # Highest Z value
        node_tag_with_max_z = node_tags[max_z_index]  # Node tag corresponding to this index

        ### lets try to open gmsh and enlight it

        return node_tag_with_max_z 
    
    @staticmethod
    def getBaseNode(gmshmodel):

        physical_groups = gmshmodel.getPhysicalGroups()
        for dim, tag in physical_groups:
            name = gmsh.model.getPhysicalName(dim, tag)
            if name == "Fix":
                group_dim = dim
                group_tag = tag
                break

        entities = gmshmodel.getEntitiesForPhysicalGroup(group_dim, group_tag)

        all_nodes = []
        
        # Loop through each entity and get the nodes
        for entity in entities:
            # Get node tags and coordinates for the entity
            node_tags = (gmshmodel.mesh.getNodes(group_dim, entity)[0])
            
            # Add the node tags to the set
            all_nodes.append(node_tags)
        
        return all_nodes
        
        
class monotonicPushoverAnalysis:
    def PushoverLcf(nSteps, cPoint, bPoints, elementTags, gmshmodel):

        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1/nSteps) #the number is the load step
        ops.algorithm("Newton")
        ops.analysis("Static")

        #Create test
        """The displacement test allows us to understand how much is the displacement changing from step to step.
        If its not changing a lot, we are reaching the convergency. - the model has converged"""
        ops.test("NormDispIncr", 1.*10**-11, 50) #the first thing is the tolerance and the second thing is the number of iteration - 50 is a good amount of iterations

        #Run analysis
        #ops.record() #this record the original status of the model
        #ok = ops.analyze(Nsteps) #not the best option, i need to use the maxDisp

        ops.analyze(nSteps)
        recorder.PushoverRecorders("Pushover_Lc_Force", "SelfWeight", cPoint, bPoints)
        #recorder.plotPushover("Pushover_Lc_Force", "Selfweight")
        visualize_eleResponse_in_gmsh(gmshmodel, elementTags, "strains", new_view_name=f"Strain distribution")


    def PushoverLcD(maxDisp, controlNode, du, controlNodeDOF, ops, elementTags, gmshmodel):

        #Define time series
        ops.timeSeries("Constant", 1)
        ops.timeSeries("Linear", 2)

        #Define loads
        ops.pattern("Plain", 1, 2)
        ops.sp(controlNode, controlNodeDOF, du) #This is the single point constraint that allows me to apply the displacement

        #Define analysis options
        """I want to check"""
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0) #the number is the load step
        ops.algorithm("Newton")
        ops.analysis("Static")

        #Create test
        """The displacement test allows us to understand how much is the displacement changing from step to step.
        If its not changing a lot, we are reaching the convergency. - the model has converged"""
        ops.test("NormDispIncr", 1.*10**-11, 50) #the first thing is the tolerance and the second thing is the number of iteration

        #Run analysis
        ops.record() #this record the original status of the model

        nn = 0

        while( ops.nodeDisp(controlNode, controlNodeDOF) < maxDisp):
            ok = ops.analyze(1)

            if ok !=0:
                ok = utils.LcBasicAnalysisLoop(ok, nn)
            
            ops.integrator("LoadControl", 1.0) #the number is the load step
            ops.algorithm("Newton")
            ops.test("NormDispIncr", 1.*10**-11, 50)

            if ok !=0:
                print("Analysis failed at load factor", nn)
                break

    def PushoverDcf(maxDisp, du, gmshmodel): #something wrong with loop

        controlNode = utils.getNodeWithHigherCoords(gmshmodel)
        controlNodeDOF = 3
        

        print(controlNode)

        #Define analysis options
        """I want to check"""
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("DisplacementControl", int(controlNode), int(controlNodeDOF), du) 
        ops.algorithm("Newton")
        ops.analysis("Static")

        #Create test
        """The displacement test allows us to understand how much is the displacement changing from step to step.
        If its not changing a lot, we are reaching the convergency. - the model has converged"""
        ops.test("NormDispIncr", 1.*10**-8, 50) #the first thing is the tolerance and the second thing is the number of iteration

        #Run analysis
        ops.record() #this record the original status of the model

        nn = 0

        while( ops.nodeDisp(int(controlNode), int(controlNodeDOF)) < maxDisp):

            ok = ops.analyze(1)

            if ok !=0:
                ok = utils.DcBasicAnalysisLoop(ok, int(controlNode), int(controlNodeDOF), du, nn)
            if ok !=0:
                print("Analysis failed at load factor", nn)
                break

        print()
        print("Analysis complete!")













