import hashlib
import itertools
import time

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================

# 1. HISTORY DATA (Period -> Result)
history = [
    { "p": "202512261000100148", "r": 0 },
    { "p": "202512261000100149", "r": 0 },
    { "p": "202512261000100150", "r": 0 },
    { "p": "202512261000100151", "r": 5 },
    { "p": "202512261000100152", "r": 9 },
    { "p": "202512261000100153", "r": 0 },
    { "p": "202512261000100154", "r": 8 },
    { "p": "202512261000100155", "r": 9 }
]

# 2. EXPANDED WORDLIST
words = [
    # --- ORIGINAL LIST ---
    "wingo", "92lottery", "secret", "admin", "salt", "key", "lottery", "hash",
    "india", "color", "win", "prediction", "server", "private", "public",
    "tiranga", "damang", "tc", "bdg", "bigcash", "fastwin", "mantrimalls",
    "god", "shiva", "lucky", "money", "rich", "success", "winner", "play",
    "node", "express", "mysql", "token", "auth", "veri", "invite", "code",
    "123456", "000000", "888888", "999999", "qwerty", "password", "admin123",
    "2025", "2024", "111", "222", "333", "555", "777",
    "wingo1", "wingo3", "wingo5", "wingo10", "minutes_1", "users", "level",
    "roses", "roses_f1", "roses_today", "point_list", "product_id",
    "@", "#", "$", "_", "-", "|", ":", ".", "!", "?", "*",

    # --- NEW ADDITIONS ---
    # Game Outcomes
    "big", "small", "red", "green", "violet", "purple", "blue",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "odd", "even", "random", "fix", "fixed", "result", "period",
    
    # Common Admin/System
    "root", "toor", "master", "super", "manager", "support", "service",
    "api", "dev", "prod", "test", "staging", "local", "host", "db", "sql",
    "login", "user", "pass", "change", "update", "delete", "create",
    
    # Financial / Crypto
    "usdt", "trx", "bnb", "btc", "eth", "wallet", "bank", "pay", "payment",
    "bonus", "commission", "referral", "agent", "vip", "pro", "max",
    
    # Common Years & numbers
    "2020", "2021", "2022", "2023", "2026", "123", "1234", "12345",
    
    # Short words & separators
    "a", "b", "c", "x", "y", "z", "ok", "go", "do", "is", "am",
    "&", "+", "=", "/"
]

# 3. SETTINGS
# 1 = "wingo"
# 2 = "wingo2025"
# 3 = "wingo2025admin" (WARNING: MILLIONS OF CHECKS)
MAX_COMBINATION_LENGTH = 3 

# ==========================================
# 🛠️ ENGINE LOGIC
# ==========================================

def get_hash(algo, input_str):
    encoded = input_str.encode('utf-8')
    if algo == 'md5': return hashlib.md5(encoded).hexdigest()
    if algo == 'sha256': return hashlib.sha256(encoded).hexdigest()
    if algo == 'sha1': return hashlib.sha1(encoded).hexdigest()
    return None

def check_history(algo, salt, type_mode):
    """Checks if a salt works for the ENTIRE history."""
    for item in history:
        # Construct Payload
        if type_mode == "suffix":
            payload = str(item["p"]) + salt
        else:
            payload = salt + str(item["p"])
            
        hash_hex = get_hash(algo, payload)
        
        try:
            last_char = hash_hex[-1]
            calc = int(last_char, 16) % 10
        except:
            return False
            
        if calc != item["r"]:
            return False
    return True

def main():
    print(f"🚀 STARTING COMBO BRUTE FORCE")
    print(f"📦 Wordlist Size: {len(words)}")
    print(f"🔗 Max Combination Length: {MAX_COMBINATION_LENGTH}")
    print("-" * 40)

    start_time = time.time()
    algorithms = ['md5', 'sha256', 'sha1']
    total_checks = 0
    found = False

    # Iterate through combination lengths (1, 2, 3...)
    for length in range(1, MAX_COMBINATION_LENGTH + 1):
        print(f"\n[+] Generating combinations of length {length}...")
        
        combos = itertools.product(words, repeat=length)
        
        for combo_tuple in combos:
            salt_candidate = "".join(combo_tuple)
            
            total_checks += 1
            if total_checks % 500000 == 0:
                print(f"    Checked {total_checks} combinations... (Current: {salt_candidate})")

            for algo in algorithms:
                # Test Suffix
                if check_history(algo, salt_candidate, "suffix"):
                    print(f"\n🎉 CRACKED! SALT FOUND!")
                    print(f"🔑 SALT: \"{salt_candidate}\"")
                    print(f"🛠️  ALGO: {algo}")
                    print(f"📍 TYPE: Suffix (Period + Salt)")
                    found = True
                    break
                
                # Test Prefix
                if check_history(algo, salt_candidate, "prefix"):
                    print(f"\n🎉 CRACKED! SALT FOUND!")
                    print(f"🔑 SALT: \"{salt_candidate}\"")
                    print(f"🛠️  ALGO: {algo}")
                    print(f"📍 TYPE: Prefix (Salt + Period)")
                    found = True
                    break
            
            if found: break
        if found: break

    elapsed = time.time() - start_time
    print("-" * 40)
    print(f"🏁 Finished in {elapsed:.2f} seconds.")
    print(f"🔍 Total Salts Checked: {total_checks}")
    
    if not found:
        print("\n❌ NO MATCH FOUND.")
        print("This suggests the salt is random alphanumeric (not in wordlist) or results are manually rigged.")

if __name__ == "__main__":
    main()