#!/usr/bin/env python3
"""
Keygen for ARM/Linux keygenme
Based on reverse engineering the validation routine in sub_610
"""

def generate_key():
    """
    Generate a valid key for the ARM keygenme.
    
    From the decompiled code analysis:
    - The validation uses character lookup tables
    - String fragments suggest "arm_kgme1" or similar patterns
    - Numeric values "00000014524" and "144" appear in the code
    
    The validation at sub_610 appears to check characters against
    a lookup table indexed by the character value.
    """
    
    # Based on the string fragments in the disassembly comments
    # and the validation logic structure, the key appears to be:
    key = "arm_kgme1"
    
    return key

def generate_alternative_keys():
    """
    Generate alternative possible keys based on other patterns
    observed in the code.
    """
    alternatives = [
        "arm_kgme1",
        "rm_kgme1", 
        "m_kgme1",
        "kgme1",
    ]
    
    return alternatives

if __name__ == "__main__":
    print("ARM/Linux Keygenme Keygen")
    print("=" * 40)
    print()
    
    main_key = generate_key()
    print(f"Primary key: {main_key}")
    print()
    
    print("Alternative keys to try:")
    for i, key in enumerate(generate_alternative_keys(), 1):
        print(f"  {i}. {key}")
    print()
    
    print("Note: The most likely valid key is 'arm_kgme1'")
    print("based on the validation logic patterns.")
