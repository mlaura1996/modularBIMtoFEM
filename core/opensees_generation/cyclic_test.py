from core.config import ops, pd, gmsh
from external.gmsh2opensees import *

# Load estimated time series with displacement data
file_path = "CT02_estimated_time_series.csv"  # Ensure this file is available
df = pd.read_csv(file_path)

# Extract time and displacement values
time_values = df['Estimated Time (s)'].values  # Time steps
displacement_values = df['Ux_top [mm]'].values  # Displacement history at top of the wall

# Get all nodes in the Gmsh physical group 'loads'
loads_nodes, _, _, _ = get_elements_and_nodes_in_physical_group("loads", gmsh.model)

# Define OpenSees Model
ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 3)  # 3D model with 3 DOF per node

# Apply Time Series for Cyclic Loading
ops.timeSeries("Path", 2, "-dt", time_values[1] - time_values[0], "-values", *displacement_values)

# Define Load Pattern
ops.pattern("Plain", 2, 2)

# Apply distributed cyclic load across all nodes in 'loads'
load_factor = 1.0 / len(loads_nodes)  # Distribute load equally
for node in loads_nodes:
    ops.load(node, load_factor, 0, 0)  # Load in X-direction

# Define Displacement Control
ops.integrator("DisplacementControl", loads_nodes[0], 1, 0.5)  # Control first node in 'loads'

# Run Analysis
ops.system("BandGeneral")
ops.numberer("RCM")
ops.constraints("Transformation")
ops.test("NormDispIncr", 1e-8, 10, 0)
ops.algorithm("Newton")
ops.analysis("Static")

for i in range(len(time_values)):
    ops.analyze(1)
    disp = ops.nodeDisp(loads_nodes[0], 1)
    print(f"Step {i}: Time = {time_values[i]:.2f} s, Disp = {disp:.5f} mm")