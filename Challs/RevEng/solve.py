#!/usr/bin/env python3
"""
Quick VM Flag Solver - Automated approach
"""

import angr
import claripy

binary_path = input("Enter the path to the binary file: ").strip()

print("[*] Loading binary...")
p = angr.Project(binary_path, auto_load_libs=False)

# Create 16-byte symbolic flag
flag = claripy.BVS('flag', 16 * 8)

print("[*] Setting up symbolic execution...")
state = p.factory.entry_state(args=[binary_path, flag])

# Constrain to printable ASCII
for i in range(16):
    byte = flag.get_byte(i)
    state.solver.add(byte >= 0x20)
    state.solver.add(byte <= 0x7e)

simgr = p.factory.simulation_manager(state)

print("[*] Running... (this will take 5-15 minutes)")
print("[*] Press Ctrl+C if it takes longer than 20 minutes")

# Run until completion, avoiding error exits
simgr.explore(
    avoid=[0x001017d4, 0x0010198c, 0x00101c8e]
)

# Check all deadended states (completed normally)
print(f"\n[*] Checking {len(simgr.deadended)} completed paths...")

for state in simgr.deadended:
    output = state.posix.dumps(1)
    # Skip if only has the waiting message
    if output and len(output) > 100:
        try:
            solution = state.solver.eval(flag, cast_to=bytes).decode('ascii')
            print(f"\n[+] FLAG FOUND: {solution}")
            print(f"[+] Output:\n{output.decode('ascii', errors='replace')}")
            break
        except:
            pass
else:
    print("[-] No flag found in completed states")
    print(f"[*] Active states: {len(simgr.active)}")
    
    # Try active states too
    for state in simgr.active[:5]:
        try:
            solution = state.solver.eval(flag, cast_to=bytes).decode('ascii')
            print(f"\n[?] Possible flag: {solution}")
        except:
            pass
