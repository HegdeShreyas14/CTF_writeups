#!/usr/bin/env python3
"""
exploit_full.py

- Solves SLOTH PoW using the official solver (downloaded at runtime)
- Enumerates secret path via check_path (tries all unused nodes)
- Saves lwe_error_magnitudes to errors_from_server.json
- Loads public LWE params from lwe_pub_params.json and recovers s
- Submits get_flag and prints the server response

Requirements:
 - Python 3
 - curl (to fetch the official pow solver)
 - graph.json and lwe_pub_params.json in current directory
 - Network access to the target host/port

Usage:
  python3 exploit_full.py <host> <port>
"""

import socket
import re
import json
import time
import base64
import sys
import tempfile
import subprocess
import os
from copy import deepcopy

# Constants
POW_URL = "https://goo.gle/kctf-pow"
VERSION = 's'
MODULUS = 2**1279 - 1
TIMEOUT_SECONDS = 300

# ------------------ Helpers: Networking ------------------
def recv_all(sock, timeout=0.2):
    sock.settimeout(timeout)
    data = b''
    try:
        while True:
            part = sock.recv(4096)
            if not part:
                break
            data += part
    except socket.timeout:
        pass
    return data.decode(errors='ignore')

def send_line(sock, line):
    if not line.endswith("\n"):
        line = line + "\n"
    sock.sendall(line.encode())

# ------------------ Helpers: PoW solve (official solver) ------------------
def solve_pow_with_official(chal):
    """
    Download the official pow solver and run:
      python3 pow.py solve <challenge>
    Returns the solution string (like 's.<...>') or None.
    """
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
    tf.close()
    try:
        # download
        curl = subprocess.run(["curl", "-sSL", POW_URL], stdout=open(tf.name, "wb"))
        # run solver
        proc = subprocess.run(["python3", tf.name, "solve", chal],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        out = proc.stdout.strip()
        if out == "":
            # sometimes solver prints to stderr
            out = proc.stderr.strip()
        # expect an 's.' prefixed string in out
        m = re.search(r'(s\.[A-Za-z0-9+/=]+)', out)
        if m:
            return m.group(1)
        # otherwise, if the solver prints the full encoded string (two parts)
        m2 = re.search(r'(s\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+)', out)
        if m2:
            return m2.group(1)
        return out if out.startswith("s.") else None
    finally:
        try:
            os.remove(tf.name)
        except:
            pass

# ------------------ LWE: modular linear algebra ------------------
def egcd(a, b):
    if b == 0:
        return (1, 0, a)
    x, y, g = egcd(b, a % b)
    return (y, x - (a // b) * y, g)

def inv_mod(a, m):
    a %= m
    x, y, g = egcd(a, m)
    if g != 1:
        return None
    return x % m

def gauss_mod(A_rows, b_vec, q):
    """
    Solve A_rows * x = b_vec (mod q).
    Returns (solution_vector_length_n, rank) or (None, 0) if inconsistent.
    """
    A = [list(map(lambda v: v % q, row)) for row in A_rows]
    B = [v % q for v in b_vec]
    m = len(A)
    n = len(A[0]) if m > 0 else 0
    row = 0
    where = [-1] * n
    for col in range(n):
        sel = -1
        for r in range(row, m):
            if A[r][col] % q != 0:
                sel = r
                break
        if sel == -1:
            continue
        A[row], A[sel] = A[sel], A[row]
        B[row], B[sel] = B[sel], B[row]
        inv = inv_mod(A[row][col], q)
        if inv is None:
            return None, 0
        # normalize pivot row
        for c in range(col, n):
            A[row][c] = (A[row][c] * inv) % q
        B[row] = (B[row] * inv) % q
        # eliminate others
        for r in range(m):
            if r != row and A[r][col] != 0:
                factor = A[r][col]
                for c in range(col, n):
                    A[r][c] = (A[r][c] - factor * A[row][c]) % q
                B[r] = (B[r] - factor * B[row]) % q
        where[col] = row
        row += 1
        if row == m:
            break
    # consistency check
    for r in range(row, m):
        allzero = True
        for c in range(n):
            if A[r][c] % q != 0:
                allzero = False
                break
        if allzero and (B[r] % q) != 0:
            return None, 0
    x = [0] * n
    for i in range(n):
        if where[i] != -1:
            x[i] = B[where[i]] % q
        else:
            x[i] = 0
    rank = row
    return [int(v) for v in x], rank

# ------------------ LWE: secret recovery using known abs(errors) ------------------
def recover_secret_from_public(A, b, abs_e, q, n, max_rows_to_use=None):
    """
    Backtracking search over sign choices for errors; tries to find a consistent solution s.
    """
    m = len(A)
    max_rows_to_use = max_rows_to_use or m
    rhs_candidates = []
    for i in range(m):
        e = abs_e[i] % q
        rhs_plus = (b[i] - e) % q   # if e_i = +abs_e
        rhs_minus = (b[i] + e) % q  # if e_i = -abs_e
        rhs_candidates.append((rhs_plus, rhs_minus))

    # Choose row order: prefer small abs_e and also rows with diverse A rows
    order = list(range(m))
    order.sort(key=lambda i: abs_e[i])

    best = {"sol": None}
    start_time = time.time()
    TIMEOUT = TIMEOUT_SECONDS
    sys.setrecursionlimit(10000)

    # simple caching not used; DFS with pruning on linear independence is applied by checking rank
    def dfs(pos, selected_rows, selected_rhs):
        # timeout
        if time.time() - start_time > TIMEOUT:
            return False
        # try solving if enough rows
        if len(selected_rows) >= n:
            A_sub = [A[r] for r in selected_rows]
            sol, rank = gauss_mod(A_sub, selected_rhs, q)
            if sol is not None and rank == n:
                # verify against all rows
                ok = True
                for i in range(m):
                    lhs = sum((A[i][j] * sol[j]) for j in range(n)) % q
                    if lhs != rhs_candidates[i][0] and lhs != rhs_candidates[i][1]:
                        ok = False
                        break
                if ok:
                    best["sol"] = sol
                    return True
        if pos >= len(order) or len(selected_rows) >= max_rows_to_use:
            return False

        row_idx = order[pos]
        # choose plus sign
        selected_rows.append(row_idx)
        selected_rhs.append(rhs_candidates[row_idx][0])
        if dfs(pos + 1, selected_rows, selected_rhs):
            return True
        selected_rows.pop()
        selected_rhs.pop()

        # choose minus sign
        selected_rows.append(row_idx)
        selected_rhs.append(rhs_candidates[row_idx][1])
        if dfs(pos + 1, selected_rows, selected_rhs):
            return True
        selected_rows.pop()
        selected_rhs.pop()

        # skip row
        if dfs(pos + 1, selected_rows, selected_rhs):
            return True

        return False

    ok = dfs(0, [], [])
    if ok and best["sol"] is not None:
        return best["sol"]
    return None

# ------------------ Main exploit flow ------------------
def main():
    if len(sys.argv) != 3:
        print("Usage: python3 exploit_full.py <host> <port>")
        sys.exit(1)
    host = sys.argv[1]; port = int(sys.argv[2])

    # Load graph and LWE public params (local files)
    if not os.path.exists("graph.json"):
        print("graph.json missing (you uploaded earlier). Place it here.")
        sys.exit(1)
    if not os.path.exists("lwe_pub_params.json"):
        print("lwe_pub_params.json missing. Place public LWE params here.")
        sys.exit(1)

    with open("graph.json") as f:
        graph = json.load(f)
    with open("lwe_pub_params.json") as f:
        pub = json.load(f)

    A = pub['A']
    b = pub['b']
    q = pub['lwe_q']
    n = pub['lwe_n']
    m = pub['lwe_m']

    nodes = sorted(map(int, graph.keys()))

    print("[*] Connecting to target {}:{} ...".format(host, port))
    sock = socket.create_connection((host, port), timeout=20)
    time.sleep(0.2)
    banner = recv_all(sock, timeout=1.0)
    print("[Server banner]\n", banner)

    # find PoW challenge
    m_ch = re.search(r'(s\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+)', banner)
    if not m_ch:
        # nudge and read again
        send_line(sock, "")
        time.sleep(0.2)
        banner = recv_all(sock, timeout=1.0)
        print("[Server banner 2]\n", banner)
        m_ch = re.search(r'(s\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+)', banner)

    if not m_ch:
        print("[!] PoW challenge not found in banner — aborting.")
        sock.close()
        sys.exit(1)

    challenge = m_ch.group(1)
    print("[*] PoW challenge:", challenge)
    print("[*] Solving PoW with official solver (this may take a little time)...")
    solution = solve_pow_with_official(challenge)
    if not solution:
        print("[!] Failed to solve PoW with official solver.")
        sock.close()
        sys.exit(1)
    print("[*] PoW solution:", solution)

    # submit solution line; the server prints "Solution?" earlier, so this will answer it
    send_line(sock, solution)
    time.sleep(0.3)
    after_pow = recv_all(sock, timeout=1.0)
    print("[After PoW]\n", after_pow)

    # enumerate full path by trying all unused nodes each step
    path = []
    print("[*] Starting path enumeration (this will try all unused nodes per position)...")
    for pos in range(len(nodes)):
        candidates = [n for n in nodes if n not in path]
        found = False
        for c in candidates:
            cmd = {"command": "check_path", "segment": path + [c]}
            send_line(sock, json.dumps(cmd))
            # small pause
            time.sleep(0.04)
            resp = recv_all(sock, timeout=0.5)
            # parse last JSON line if present
            parsed = None
            try:
                parsed = json.loads(resp.strip().splitlines()[-1])
            except Exception:
                parsed = None
            if parsed and parsed.get("status") == "valid_prefix":
                path.append(c)
                print(f"[+] pos={pos} -> {c}")
                found = True
                break
            if parsed and parsed.get("status") == "path_complete":
                path.append(c)
                abs_errors = parsed.get("lwe_error_magnitudes")
                print("[+] PATH COMPLETE:", path)
                print("[+] Error magnitudes length:", len(abs_errors))
                with open("errors_from_server.json", "w") as ef:
                    json.dump(abs_errors, ef)
                # try to recover s now
                print("[*] Attempting LWE secret recovery using lwe_pub_params.json ...")
                s_recovered = recover_secret_from_public(A, b, abs_errors, q, n)
                if s_recovered:
                    print("[+] Recovered s:")
                    print(s_recovered)
                    # submit get_flag
                    payload = {"command": "get_flag", "lwe_secret_s": s_recovered}
                    send_line(sock, json.dumps(payload))
                    time.sleep(0.3)
                    resp_flag = recv_all(sock, timeout=2.0)
                    print("[Flag response]\n", resp_flag)
                    sock.close()
                    return
                else:
                    print("[!] Failed to recover s automatically. Saved errors to errors_from_server.json.")
                    sock.close()
                    return
        if not found:
            print(f"[!] Could not find a valid candidate for position {pos}. Aborting enumeration.")
            sock.close()
            sys.exit(1)

    print("[!] Enumeration ended without path_complete.")
    sock.close()

if __name__ == "__main__":
    main()

