import openseespy.opensees as ops
import numpy as np
import matplotlib.pyplot as plt
from damage_law import * 
import vfo.vfo as vfo
import csv

# Unità: mm, N, MPa (1 MPa = 1 N/mm2)

# 1. Modello
ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 3)

# 2. Nodi: cubo 10x10x10 mm
L = 148.26  # lato cubo [mm]

# the material (units = N, mm)
E = 2850.0
v = 0.33
fc = 2.8
ft = 0.05
f0 = fc/3
ec = 0.002
Gt = 0.012
Gc = 4.56
ec = 2.0*fc/E

ep = (f0/E)*(1/3)
lt = 2.0 * E * Gc / (f0 * f0)
print("lt:")
print(lt)

print("L:")
print(L)

#Traction
Te, Ts, Td = ConstitutiveLaws.ExponentialSoftening_Tension.tension(E, ft, Gt, L)

#Compression
Ce, Cs, Cd = ConstitutiveLaws.BezierCurve_Compression.compression(E, f0, fc, Gc, L)
#Ce, Cs, Cd = ASDConcrete3D_MakeLaws._make_compression(E, f0, ec, Gt/L)

coords = [
    [0, 0, 0],   # nodo 1
    [L, 0, 0],   # nodo 2
    [L, L, 0],   # nodo 3
    [0, L, 0],   # nodo 4
    [0, 0, L],   # nodo 5
    [L, 0, L],   # nodo 6
    [L, L, L],   # nodo 7
    [0, L, L],   # nodo 8
]

for i, xyz in enumerate(coords):
    ops.node(i+1, *xyz)

# 3. Vincoli: base bloccata (z=0)
# for node in [1, 2, 3, 4]:
#     #ops.fix(node, 1,1,1)
#     if node == 1 or node == 3:
#         ops.fix(node, 0, 0, 1)
#     elif node == 4:
#         ops.fix(node, 1, 0, 1)
#     else:
#         ops.fix(node, 0, 1, 1)

for node in [1, 2, 3, 4]:
    ops.fix(node, 0, 0, 1)


# 4. Materiale: Elastico 3D (E=30.000 MPa, ν=0.2)
lch = (L * L * 2*L)**(1/3) 

matTag = 1
# the plane stress
ops.nDMaterial('ASDConcrete3D', 1,
            E, v, # elasticity
            '-Te', *Te, '-Ts', *Ts, '-Td', *Td, # tensile law
            '-Ce', *Ce, '-Cs', *Cs, '-Cd', *Cd, # compressive law
            'implex'
            )

# 5. Elemento brick
eleNodes = [1, 2, 3, 4, 5, 6, 7, 8]
ops.element('stdBrick', 1, *eleNodes, matTag)

# 6. Pattern di carico: Spostamento verticale sui nodi superiori
#    Compressione: uz_negativo, Tensione: uz_positivo
sigma_target = -0.2
u_target = sigma_target*L  # [mm] -> compr

ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
for node in [5, 6, 7, 8]:
    ops.load(node, 0, 0, 1)

model = vfo.createODB(model="model", loadcase="pressure")
#vfo.plot_model("model")

# 7. Recorder: reazione sui nodi base e forza verticale totale
# --- Recorder: stress/strain agli integration points dell'elemento 1
ops.recorder('Element', '-file', 'brick_stress.out', '-time', '-ele', 1, 'stress')
ops.recorder('Element', '-file', 'brick_strain.out', '-time', '-ele', 1, 'strain')

ops.recorder('Node', '-file', 'base_reaction.out', '-time', '-node', 1, 2, 3, 4, '-dof', 3, 'reaction')
ops.recorder('Node', '-file', 'top_disp.out', '-time', '-node', 5, '-dof', 3, 'disp')

# 8. Analisi statica
ops.system('BandGeneral')
ops.constraints('Transformation')
ops.numberer('Plain')
ops.test('NormDispIncr', 1e-2, 10)
ops.algorithm('ModifiedNewton')
nSteps = 1000
dU = u_target / nSteps
ops.integrator('DisplacementControl', 5, 3, dU)
ops.analysis('Static')

for i in range(nSteps):
    ok = ops.analyze(1)
    if ok != 0:
        print(f"Analysis failed at step {i+1}")
        break


#vfo.plot_deformedshape("model", "pressure")

#9. Elabora risultati: leggi forze di reazione e spostamenti
base_forces = np.loadtxt('base_reaction.out')
top_disp = np.loadtxt('top_disp.out')

# Somma le reazioni alla base
Rz = base_forces[:,1:].sum(axis=1)   # N

# Deformazione ingegneristica (strain)
disp = top_disp[:,1]                 # [mm]
strain = disp / L                   # senza unità

# Tensione (stress) nominale [MPa]
A = L*L          # mm2
stress = - Rz / A / 1.0     # [N/mm2 = MPa]



# 10. Grafico Tensione-Deformazione
plt.figure()
plt.plot(strain, stress, label='Brick')
plt.xlabel('Strain ($\epsilon$)')
plt.ylabel('Stress ($\sigma$) [MPa]')
plt.title('Stress-Strain\nBrick')
plt.xlim(0, -0.03)

plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()

# 11. Esporta strain-stress in CSV
with open("stress_strain_curve_compression_2y_4x.csv", "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["Strain", "Stress [MPa]"])
    for e, s in zip(strain, stress):
        writer.writerow([e, s])

print("✅ CSV salvato: stress_strain_curve_opp.csv")

