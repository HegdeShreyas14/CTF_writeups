#!/usr/bin/env python3
"""
lwe_solver_fast.py

Usage:
  python3 lwe_solver_fast.py lwe_pub_params.json errors_from_server.json

Output:
  - prints recovered `s` vector (list of ints)
  - prints a JSON payload ready to send: {"command":"get_flag","lwe_secret_s":[...]}
  - writes /mnt/data/recovered_s.json if run in contest-like env

Notes:
 - Requires gmpy2 (recommended) and numpy (optional). If gmpy2 is absent the script still runs with pure Python ints but will be slower.
"""

import json, time, sys, os, random
from math import inf

try:
    import gmpy2
    mpz = gmpy2.mpz
    HAVE_GMP = True
except Exception:
    HAVE_GMP = False
    mpz = int

# ---------- Linear algebra helpers (mod q) ----------
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
    Solve A_rows * x = b_vec (mod q). Rectangular rows x n.
    Returns (sol, rank) where sol is one solution (free vars = 0) or (None,0) if inconsistent.
    """
    # Work on copies
    A = [list(map(lambda v: int(v % q), row)) for row in A_rows]
    B = [int(v % q) for v in b_vec]
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
        # normalize
        for c in range(col, n):
            A[row][c] = (A[row][c] * inv) % q
        B[row] = (B[row] * inv) % q
        # eliminate other rows
        for r in range(m):
            if r != row and A[r][col] != 0:
                factor = A[r][col]
                # subtract factor * pivot row
                for c in range(col, n):
                    A[r][c] = (A[r][c] - factor * A[row][c]) % q
                B[r] = (B[r] - factor * B[row]) % q
        where[col] = row
        row += 1
        if row == m:
            break
    # consistency
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
    return [int(v) for v in x], row

def rank_mod(A_rows, q):
    """
    Return rank (mod q) of matrix A_rows (list of row lists).
    Efficient enough for incremental checks.
    """
    if not A_rows:
        return 0
    A = [list(map(lambda v:int(v % q), row)) for row in A_rows]
    m = len(A); n = len(A[0])
    r = 0
    for c in range(n):
        sel = -1
        for i in range(r, m):
            if A[i][c] % q != 0:
                sel = i; break
        if sel == -1:
            continue
        A[r], A[sel] = A[sel], A[r]
        inv = inv_mod(A[r][c], q)
        if inv is None:
            continue
        for j in range(c, n):
            A[r][j] = (A[r][j] * inv) % q
        for i in range(m):
            if i != r and A[i][c] != 0:
                factor = A[i][c]
                for j in range(c, n):
                    A[i][j] = (A[i][j] - factor * A[r][j]) % q
        r += 1
        if r == m:
            break
    return r

# ---------- Main solver logic ----------
def recover_secret(A, b, abs_e, q, n, time_limit=300):
    """
    Attempts to recover s given public A,b and absolute errors abs_e.
    Returns list s or None.
    """
    m = len(A)
    assert len(b) == m and len(abs_e) == m
    # prepare RHS candidates
    rhs = []
    for i in range(m):
        e = int(abs_e[i]) % q
        rhs.append(((b[i] - e) % q, (b[i] + e) % q))
    # sort rows: prefer small errors (more reliable)
    order = list(range(m))
    order.sort(key=lambda i: abs_e[i])
    # greedy build independent pool of rows
    pool = []
    pool_set = set()
    cur_rank = 0
    for idx in order:
        if len(pool) >= n*2:  # keep pool moderately sized
            break
        new_rank = rank_mod([A[r] for r in pool + [idx]], q)
        if new_rank > cur_rank:
            pool.append(idx)
            pool_set.add(idx)
            cur_rank = new_rank
        # stop early if we have at least n independent rows
        if cur_rank >= n:
            break
    # ensure pool large enough; if not, add rest of order until rank >= n
    if cur_rank < n:
        for idx in order:
            if idx in pool_set: continue
            new_rank = rank_mod([A[r] for r in pool + [idx]], q)
            if new_rank > cur_rank:
                pool.append(idx); pool_set.add(idx); cur_rank = new_rank
            if cur_rank >= n: break
    # if still insufficient, fallback to include more
    if cur_rank < n:
        for idx in order:
            if idx in pool_set: continue
            pool.append(idx); pool_set.add(idx)
            if len(pool) >= n*3: break

    # Trim pool to a manageable size (e.g., 70 rows)
    MAX_POOL = min(len(pool), 80)
    pool = pool[:MAX_POOL]

    print(f"[+] Pool size: {len(pool)}, estimated rank: {rank_mod([A[r] for r in pool], q)}")

    start = time.time()
    TIMEOUT = time_limit

    # Backtracking with rank-increase pruning among pool rows
    best = {"sol": None}
    visited = 0

    def dfs(i_pos, selected_rows, selected_rhs, cur_rank):
        nonlocal visited
        visited += 1
        if time.time() - start > TIMEOUT:
            return False
        # If enough rows, try solve
        if len(selected_rows) >= n:
            sol, rank = gauss_mod([A[r] for r in selected_rows], selected_rhs, q)
            if sol is not None and rank == n:
                # verify consistency against all rows
                ok = True
                for r_all in range(m):
                    lhs = sum((A[r_all][j] * sol[j]) for j in range(n)) % q
                    if lhs != rhs[r_all][0] and lhs != rhs[r_all][1]:
                        ok = False; break
                if ok:
                    best["sol"] = sol
                    return True
        if i_pos >= len(pool):
            return False
        # iterate candidates from i_pos..end
        for k in range(i_pos, len(pool)):
            r_idx = pool[k]
            if r_idx in selected_rows:
                continue
            # check rank increase if added
            new_rank = rank_mod([A[r] for r in selected_rows + [r_idx]], q)
            if new_rank <= cur_rank:
                continue
            # try plus
            selected_rows.append(r_idx)
            selected_rhs.append(rhs[r_idx][0])
            if dfs(k+1, selected_rows, selected_rhs, new_rank):
                return True
            selected_rows.pop(); selected_rhs.pop()
            # try minus
            selected_rows.append(r_idx)
            selected_rhs.append(rhs[r_idx][1])
            if dfs(k+1, selected_rows, selected_rhs, new_rank):
                return True
            selected_rows.pop(); selected_rhs.pop()
            # optionally try skipping r_idx (we already will in loop)
        return False

    # initial greedy attempt: pick first n rows from pool and try sign choices for top few
    initial_rows = []
    cur_rank = 0
    for r in pool:
        new_rank = rank_mod([A[idx] for idx in initial_rows + [r]], q)
        if new_rank > cur_rank:
            initial_rows.append(r)
            cur_rank = new_rank
        if cur_rank >= n:
            break

    print(f"[+] initial_rows count {len(initial_rows)}, rank {cur_rank}")

    # try some randomized sign assignments on initial_rows if valid
    # generate basic RHS with -abs_e sign as baseline
    base_rhs = [(b[r] - int(abs_e[r])) % q for r in initial_rows]
    sol0, rank0 = gauss_mod([A[r] for r in initial_rows], base_rhs, q) if len(initial_rows) >= n else (None, 0)
    if sol0 is not None and rank0 == n:
        # verify full consistency
        ok = True
        for r_all in range(m):
            lhs = sum((A[r_all][j] * sol0[j]) for j in range(n)) % q
            if lhs != rhs[r_all][0] and lhs != rhs[r_all][1]:
                ok = False; break
        if ok:
            print("[+] Found solution from initial greedy set")
            return sol0

    # otherwise run recursive search
    print("[*] Starting recursive search (pool size {})...".format(len(pool)))
    ok = dfs(0, [], [], 0)
    print("[*] DFS finished, visited nodes:", visited, "time:", time.time()-start)
    if best["sol"] is not None:
        return best["sol"]

    # fallback randomized sampling of n independent rows and sign flips
    print("[*] Fallback: random subset trials...")
    rows_all = pool[:]  # prefer pool
    TRIALS = 2000
    for t in range(TRIALS):
        # greedy choose n independent rows
        chosen = []
        for r in rows_all:
            if len(chosen) >= n: break
            rr = rank_mod([A[idx] for idx in chosen + [r]], q)
            if rr > rank_mod([A[idx] for idx in chosen], q):
                chosen.append(r)
        if len(chosen) < n:
            # fill randomly
            chosen = chosen + random.sample([r for r in range(m) if r not in chosen], n - len(chosen))
        # baseline rhs = minus sign
        rhs_base = [ (b[r] - int(abs_e[r])) % q for r in chosen ]
        sol_try, rank_try = gauss_mod([A[r] for r in chosen], rhs_base, q)
        if sol_try is not None and rank_try == n:
            ok_all = True
            for r_all in range(m):
                lhs = sum((A[r_all][j] * sol_try[j]) for j in range(n)) % q
                if lhs != rhs[r_all][0] and lhs != rhs[r_all][1]:
                    ok_all = False; break
            if ok_all:
                return sol_try
        # try flipping signs for top few largest errors in chosen
        topk = sorted(range(len(chosen)), key=lambda i: abs_e[chosen[i]], reverse=True)[:6]
        from itertools import product
        for mask in product([0,1], repeat=len(topk)):
            rhs_try = []
            for i_idx, r in enumerate(chosen):
                if i_idx in topk:
                    k = topk.index(i_idx)
                    if mask[k] == 0:
                        rhs_try.append((b[r] - int(abs_e[r])) % q)
                    else:
                        rhs_try.append((b[r] + int(abs_e[r])) % q)
                else:
                    rhs_try.append((b[r] - int(abs_e[r])) % q)
            sol2, rank2 = gauss_mod([A[r] for r in chosen], rhs_try, q)
            if sol2 is not None and rank2 == n:
                ok_all = True
                for r_all in range(m):
                    lhs = sum((A[r_all][j] * sol2[j]) for j in range(n)) % q
                    if lhs != rhs[r_all][0] and lhs != rhs[r_all][1]:
                        ok_all = False; break
                if ok_all:
                    return sol2
    return None

# ---------- CLI ----------
def main():
    if len(sys.argv) != 3:
        print("Usage: python3 lwe_solver_fast.py lwe_pub_params.json errors_from_server.json")
        sys.exit(1)
    pubf = sys.argv[1]; errf = sys.argv[2]
    pub = json.load(open(pubf))
    abs_e = json.load(open(errf))
    A = pub["A"]; b = pub["b"]; q = pub["lwe_q"]; n = pub["lwe_n"]; m = pub["lwe_m"]
    assert len(abs_e) == m
    print("[*] Loaded A ({}x{}), q={}, m={}".format(len(A[0]) if len(A)>0 else 0, len(A), q, m))
    st = time.time()
    s = recover_secret(A, b, abs_e, q, n, time_limit=900)
    et = time.time()
    if s is None:
        print("[!] Failed to recover s within time limit ({}s)".format(et - st))
        sys.exit(2)
    print("[+] Recovered secret s (length {}):".format(len(s)))
    print(s)
    payload = {"command":"get_flag", "lwe_secret_s": s}
    print("\nJSON payload to submit:\n")
    print(json.dumps(payload))
    # save
    try:
        open("/mnt/data/recovered_s.json","w").write(json.dumps(s))
    except Exception:
        pass

if __name__ == "__main__":
    main()
