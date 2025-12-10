#!/usr/bin/env python3
import json
from sympy import Matrix
from sympy.matrices.normalforms import lll_normal_form

def load_data(pubfile, errfile):
    pub = json.load(open(pubfile))
    A = Matrix(pub["A"])
    b = Matrix(pub["b"])
    q = pub["lwe_q"]
    abs_e = Matrix(json.load(open(errfile)))
    return A, b, q, abs_e

def build_lattice(A, b, q, abs_e):
    n = A.shape[1]
    m = A.shape[0]

    # lattice dimension
    dim = n + m + 1
    L = Matrix.zeros(dim, dim)

    # q * I_n block
    for i in range(n):
        L[i, i] = q

    # A | -I_m | b block
    for i in range(m):
        for j in range(n):
            L[n+i, j] = A[i, j]
        L[n+i, n+i] = -1          # -I_m
        L[n+i, n+m] = b[i]

    # last scaling coordinate
    L[n+m, n+m] = q

    return L

def babai_round(B, target):
    """Babai's nearest plane for SymPy matrices."""
    B = Matrix(B)
    G = (B * B.T).LUsolve(B * Matrix(target))   # Solve B*G = projection
    coeffs = [round(float(g)) for g in G]      # round coefficients
    return B.T * Matrix(coeffs)

def solve_lwe(pubfile, errfile):
    A, b, q, abs_e = load_data(pubfile, errfile)

    print("[*] Building lattice...")
    L = build_lattice(A, b, q, abs_e)

    print("[*] Running SymPy LLL reduction...")
    L_red = lll_normal_form(L)

    print("[*] Applying Babai rounding...")
    closest = babai_round(L_red, [0] * L.shape[0])

    n = A.shape[1]
    # secret approx = closest[i] / q (mod q)
    s = [int(closest[i] // q) % q for i in range(n)]
    return s

def verify_solution(A, b, q, abs_e, s):
    s = Matrix(s)
    for i in range(A.shape[0]):
        lhs = (A[i, :] * s) % q
        rhs1 = (b[i] - abs_e[i]) % q
        rhs2 = (b[i] + abs_e[i]) % q
        if lhs != rhs1 and lhs != rhs2:
            return False
    return True

def main():
    import sys
    if len(sys.argv) != 3:
        print("Usage: python3 solve.py lwe_pub_params.json errors.json")
        return

    pubfile, errfile = sys.argv[1], sys.argv[2]
    A, b, q, abs_e = load_data(pubfile, errfile)

    s = solve_lwe(pubfile, errfile)
    print("[+] Candidate s:", s)

    if verify_solution(A, b, q, abs_e, s):
        print("[+] Verified! Correct secret s")
        print(json.dumps({"command": "get_flag", "lwe_secret_s": s}))
    else:
        print("[!] Verification FAILED")

if __name__ == "__main__":
    main()
