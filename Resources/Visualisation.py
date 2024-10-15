import matplotlib.pyplot as plt
import numpy as np
import openseespy.opensees as ops
import gmsh
import gmshModel as gmshModel

class visualizePointsOfInterest:
    @staticmethod
    def highlight_control_point(gmshmodel, point_tag):

        pointDimTag = (0, point_tag)

        gmsh.option.set_number("Mesh.SurfaceEdges", 0)
        gmsh.option.set_number("Mesh.VolumeFaces", 1)
        gmsh.option.set_number("Mesh.ColorCarousel", 0)
        gmsh.option.setColor("Mesh.Color.Tetrahedra", 128, 128, 128)
        gmsh.option.setColor("Geometry.Color.Curves", 0, 0, 0)

        point_tags = ((gmshmodel.getEntities(dim = 0)))
        for dim, tag in point_tags:
            gmsh.model.setVisibility([(dim, tag)], 0)

        gmsh.model.setVisibility([pointDimTag], 1)

        gmsh.option.setColor("Geometry.Color.Points", 255, 0, 0)
        gmsh.option.set_number("Geometry.PointType", 1)

        
        gmshModel

        gmsh.fltk.run()


class recorder:

    @staticmethod
    def PushoverRecorders(OutDirName, AnalysisName, controlPoint, basePoint): #you can have more analysis outputs in the same directory
        
        baseName = OutDirName + "\\" + AnalysisName
        #ops.recorder('Node', '-file', baseName + "Top_Disp.out", "-time", "-nodeRange", 4, 4, "-dof", 1, 2, 3, "disp") #careful because my nodes here are explcit, while I need to chose them, see below
        ops.recorder('Node', '-file', baseName + "Top_Disp.out", "-time", "-node", [controlPoint], "-dof", 1, 2, 3, "disp") #not sure if I need to use nodeRange or nodes
        #ops.recorder('Node', '-file', baseName + "Reactions.out", "-time", "-nodeRange", 1, 1, "-dof", 1, 2, 3, "reaction") #same
        ops.recorder('Node', '-file', baseName + "Reactions.out", "-time", "-node", [basePoint], "-dof", 1, 2, 3, "reaction") #not sure if I need to use nodeRange or nodes

    @staticmethod
    def plotPushover(OutDirName, AnalysisName):
        baseName = OutDirName + "\\" + AnalysisName
        dispFileName = baseName + "Top_Disp.out"
        reactFileName = baseName + "Reactions.out"

        Disp = np.loadtxt(dispFileName, delimiter=" ")
        Reac = np.loadtxt(reactFileName, delimiter=" ")

        x = Disp[:, 1]
        shear = Reac[:, 1]
        plt.plot(x, shear)