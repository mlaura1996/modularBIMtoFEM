import math
import matplotlib.pyplot as plt
import numpy as np
import itertools as it 

def infinite_numbers(start=0, step=1):
    for k in it.count():
        yield start + k*step


# Constants
TOLERANCE = 1.0e-12

class ConstitutiveLaws:

    class BezierCurve_Compression:

            @staticmethod
            def eval_bezier(xi, x0, x1, x2, y0, y1, y2):
                A = x0 - 2.0 * x1 + x2
                B = 2.0 * (x1 - x0)
                C = x0 - xi
                if abs(A) < TOLERANCE:
                    x1 += 1.0E-6 * (x2 - x0)
                    A = x0 - 2.0 * x1 + x2
                    B = 2.0 * (x1 - x0)
                    C = x0 - xi
                if A == 0.0:
                    return 0.0
                D = B * B - 4.0 * A * C
                t = (-B + math.sqrt(D)) / (2.0 * A)
                return (y0 - 2.0 * y1 + y2) * t * t + 2.0 * (y1 - y0) * t + y0

            @staticmethod
            def eval_area(x1, x2, x3, y1, y2, y3):
                return x2 * y1 / 3.0 + x3 * y1 / 6.0 - x2 * y3 / 3.0 + x3 * y2 / 3.0 + x3 * y3 / 2.0 - x1 * (y1 / 2.0 + y2 / 3.0 + y3 / 6.0)
            
            @staticmethod
            def calc_G(sp, sk, sr, ep, ej, ek, er, eu):
                G1 = ep * sp / 2.0
                G2 = ConstitutiveLaws.BezierCurve_Compression.eval_area(ep, ej, ek, sp, sp, sk)
                G3 = ConstitutiveLaws.BezierCurve_Compression.eval_area(ek, er, eu, sk, sr, sr)
                return G1 + G2 + G3

            @staticmethod
            def stretch(S, ep, ej, ek, er, eu):
                ej += (ej - ep) * S
                ek += (ek - ep) * S
                er += (er - ep) * S
                eu += (eu - ep) * S
                return (ej, ek, er, eu)

            @staticmethod
            def getAllPoints(E, Gf, lch, s0, sp, sr, ep, c1, c2, c3):
                # fai, ad esempio:
                # scale_lch = 10.0  
                scale_lch = 1  
                Gf_bar = Gf / (scale_lch * lch)

                # Auto-calculation of other parameters
                sk = sr + (sp - sr) * c1
                e0 = s0 / E
                alpha = 2.0 * (ep - sp / E)
                ej = ep + alpha * c2
                ek = ej + alpha * (1 - c2)
                if abs(sp - sk) > 1.0e-16:
                    er = (ek - ej) / (sp - sk) * (sp - sr) + ej
                else:
                    er = ek * c3
                eu = er * c3

                # Regularization
                G_bar = ConstitutiveLaws.BezierCurve_Compression.calc_G(sp, sk, sr, ep, ej, ek, er, eu)
                G1 = sp * ep / 2.0
                stretch_value = (Gf_bar - G1) / (G_bar - G1) - 1.0
                if stretch_value <= -1.0:
                    raise ValueError(
                        f"Fracture energy (Gf = {Gf}) is too small, or the element characteristic length (lch = {lch}) is too large.\n"
                        f"Minimum Gf to avoid constitutive snap-back is {G1}\n"
                    )
                ej, ek, er, eu = ConstitutiveLaws.BezierCurve_Compression.stretch(stretch_value, ep, ej, ek, er, eu) #ej, ek, er, eu

                return ej, ek, er, eu, sk
            
            @staticmethod
            def computeValues(E, s0, sp, sr, ep, ej, ek, er, eu, e0, sk, xi, R):
                # Compute damage
                if xi <= ep:
                    s = ConstitutiveLaws.BezierCurve_Compression.eval_bezier(xi, e0, sp / E, ep, s0, sp, sp)
                elif xi <= ek:
                    s = ConstitutiveLaws.BezierCurve_Compression.eval_bezier(xi, ep, ej, ek, sp, sp, sk)
                elif xi <= eu:
                    s = ConstitutiveLaws.BezierCurve_Compression.eval_bezier(xi, ek, er, eu, sk, sr, sr)
                else:
                    s = sr
                D = 1.0 - s / R

                # Derivative
                h = max((sp - s0) / 100.0, 1.0e-8)
                xi = (R + h) / E
                if xi <= ep:
                    s = ConstitutiveLaws.BezierCurve_Compression.eval_bezier(xi, e0, sp / E, ep, s0, sp, sp)
                elif xi <= ek:
                    s = ConstitutiveLaws.BezierCurve_Compression.eval_bezier(xi, ep, ej, ek, sp, sp, sk)
                elif xi <= eu:
                    s = ConstitutiveLaws.BezierCurve_Compression.eval_bezier(xi, ek, er, eu, sk, sr, sr)
                else:
                    s = sr
                dch = 1.0 - s / (R + h)
                dDdR = (dch - D) / h

                return D, dDdR
            
            @staticmethod
            def compression(E, s0, sp, Gc, lch): 
                sr = 0.001     # Residual stress in Pascals (e.g., 50 MPa)
                ep = 0.010
                ep = (5/3)*(sp/E)

                c1 = 0.5         # Material parameter for intermediate stress
                c2 = 0.5   # Material parameter for intermediate strain
                c3 = 1        # Material parameter for residual strain

                # Compute necessary points
                ej, ek, er, eu, sk = ConstitutiveLaws.BezierCurve_Compression.getAllPoints(E, Gc, lch, s0, sp, sr, ep, c1, c2, c3)
                e0 = s0 / E

                #Initiate the vectors
                Ce = [0, e0]
                Cs = [0, s0]
                Cd = [0, 0]

                #First Bezier curve
                strain_steps = np.linspace(e0, ep, 100)
                for epsilon in strain_steps:
                    R = E * epsilon
                    xi = R / E
                    D, dDdR = ConstitutiveLaws.BezierCurve_Compression.computeValues(E, s0, sp, sr, ep, ej, ek, er, eu, e0, sk, xi, R)
                    stress = (1 - D) * R
                    Cs.append(stress)
                    Ce.append(epsilon)
                    Cd.append(D)

                strain_steps = np.linspace(ep, ek, 100)

                for epsilon in strain_steps:  
                    R = E * epsilon
                    xi = R / E
                    D, dDdR = ConstitutiveLaws.BezierCurve_Compression.computeValues(E, s0, sp, sr, ep, ej, ek, er, eu, e0, sk, xi, R)
                    stress = (1 - D) * R
                    Cs.append(stress)
                    Ce.append(epsilon)
                    Cd.append(D)

                strain_steps = np.linspace(ek, eu, 100, False)

                for epsilon in strain_steps:  
                    R = E * epsilon
                    xi = R / E
                    D, dDdR = ConstitutiveLaws.BezierCurve_Compression.computeValues(E, s0, sp, sr, ep, ej, ek, er, eu, e0, sk, xi, R)
                    stress = (1 - D) * R
                    Cs.append(stress)
                    Ce.append(epsilon)
                    Cd.append(D)

                return(Ce, Cs, Cd)

    class ExponentialSoftening_Tension:

        @staticmethod
        def compute(E, Gf, lch, s0, R):
            D = 0.0
            dDdR = 0.0
            
            if R <= s0:
                D = 0.0
                dDdR = 0.0
            else:
                r0 = s0
                # lt = 2.0 * E * Gf / (s0 * s0)
                lt = 16.0 * E * Gf / (s0 * s0)
                if lch >= lt:
                    raise ValueError(
                        f"Fracture energy (Gf = {Gf}) is too small, "
                        f"or the element characteristic length (lch = {lch}) is too large.\n"
                        f"The maximum allowed lch is 2*E*Gf/(s0^2) = {lt} with:\n"
                        f"E = {E}\nGf = {Gf}\ns0 = {s0}\n"
                    )
                Hs = lch / (lt - lch)
                A = 2.0 * Hs
                # D = 1.0 - r0 / R * math.exp(A * (1.0 - R / r0))
                D = 1.0 - ((r0 / R) * math.exp(A * ((r0 - R) / r0)))
                dDdR = (r0 + A * R) / (R * R * math.exp(A * (R / r0 - 1.0)))
                # rmin = 1.0e-8 * s0
                # if (1.0 - D) * R < rmin:
                #     D = 1.0 - rmin / R
                #     dDdR = rmin / (R * R)
            
            return D, dDdR

        
        @staticmethod
        def tension(E, s0, Gf, lch):
            e0 = s0 / E

            Te = [0, e0]
            Ts = [0, s0]
            Td = [0, 0]
            de = 0.0001
            strain_steps = infinite_numbers(e0, de)
            
            stress = s0
 
            for epsilon in strain_steps:
                if stress > s0*0.05: #OLD
                #if stress > s0*0.005:
                #if stress > s0*0.00000005:
                    R = E * epsilon
                    D, dDdR = ConstitutiveLaws.ExponentialSoftening_Tension.compute(E, Gf, lch, s0, R)
                    stress = (1 - D) * R
                    Ts.append(stress)
                    Te.append(epsilon)
                    Td.append(D)
                else:
                    break

            return(Te, Ts, Td)
        

