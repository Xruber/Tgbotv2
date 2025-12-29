import threading
import time
import requests
import hashlib
import itertools
import asyncio
from telegram import Bot
from config import ADMIN_ID, BOT_TOKEN

# --- CONFIGURATION ---
TARGET_WINDOW_SIZE = 1000  # Keep exactly the last 1000 rounds
MAX_COMBINATION_LENGTH = 3

# GLOBAL STORAGE - Main.py reads this for the Live Monitor
LATEST_RESULTS = {
    "30s": {
        "salt": "Initializing...", 
        "acc": 0.0, 
        "total_scanned": 0,
        "current_period": "Waiting...",
        "last_update": "..."
    },
    "1m": {
        "salt": "Initializing...", 
        "acc": 0.0, 
        "total_scanned": 0,
        "current_period": "Waiting...",
        "last_update": "..."
    }
}

# URLs
URL_30S = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
URL_1M = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

# Wordlist (Your original list)
SALTS = [
    "admin", "sb", "wingo", "manager", "developer", "test",
    "123456", "password", "secret", "key", "public", "private",
    "win", "lottery", "game", "server", "hash", "salt",
    "node", "js", "api", "v1", "v2", "v3", "v4", "v5",
    "2024", "2025", "2026", "2023", "111", "888", "999",
    "big", "small", "red", "green", "violet",
    "wingo1", "wingo3", "wingo5", "wingo30", "wingo1m",
    "tr", "trx", "usdt", "btc", "eth",
    "@", "#", "$", "%", "&", "+", "-", "_", ".",
    "" 
]

class SaltCrackerWorker(threading.Thread):
    def __init__(self, game_type, api_url, bot_token, admin_id):
        threading.Thread.__init__(self)
        self.game_type = game_type
        self.api_url = api_url
        self.bot = Bot(token=bot_token)
        self.admin_id = admin_id
        self.history = [] # Sliding window of history
        self.running = True

    def get_prediction(self, period, salt):
        # Logic: SHA256(Period + "+" + Salt)
        data_str = str(period) + "+" + str(salt)
        hash_hex = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
        digit = None
        for char in reversed(hash_hex):
            if char.isdigit():
                digit = int(char)
                break
        if digit is None: return None
        return "Small" if digit <= 4 else "Big"

    def fetch_latest(self):
        try:
            ts = int(time.time() * 1000)
            url = f"{self.api_url}?ts={ts}&page=1&size=10"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.92lottery.com/"
            }
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            raw_list = data.get('data', {}).get('list', [])
            
            new_items = []
            for item in raw_list:
                period = str(item['issueNumber'])
                # Only add if newer than what we have
                if not any(x['p'] == period for x in self.history):
                    new_items.append({
                        'p': period, 
                        'r': "Small" if int(item['number']) <= 4 else "Big"
                    })
            # Return reversed so we process oldest -> newest if multiple come in
            return new_items[::-1] 
        except Exception as e:
            return []

    def analyze_window(self):
        """Analyzes the current self.history window to find best salt."""
        # Only analyze if we have enough data (e.g., at least 50 periods)
        if len(self.history) < 50:
            self.update_status(salt="Gathering Data...", acc=0)
            return

        best_score = -1
        best_salt = "None"
        total = len(self.history)
        
        # Fast Brute Force
        # Note: If history is 1000 items, this loop runs 1000 times per salt.
        for length in range(1, MAX_COMBINATION_LENGTH + 1):
            combos = itertools.product(SALTS, repeat=length)
            for combo in combos:
                salt_candidate = "".join(combo)
                
                correct = 0
                for item in self.history:
                    if self.get_prediction(item['p'], salt_candidate) == item['r']:
                        correct += 1
                
                if correct > best_score:
                    best_score = correct
                    best_salt = salt_candidate

        # Update the Global Variable immediately
        acc = (best_score / total) * 100
        self.update_status(best_salt, acc)
        print(f"[{self.game_type}] ♻️ Window Updated | Period: {self.history[-1]['p']} | Best: {best_salt} ({acc:.2f}%)")

    def update_status(self, salt, acc):
        latest_period = self.history[-1]['p'] if self.history else "Waiting..."
        LATEST_RESULTS[self.game_type] = {
            "salt": salt,
            "acc": round(acc, 2),
            "total_scanned": len(self.history),
            "current_period": latest_period,
            "last_update": time.strftime("%H:%M:%S")
        }

    def run(self):
        print(f"✅ Live Service Started: Wingo {self.game_type}")
        while self.running:
            try:
                # 1. Fetch New Data
                new_items = self.fetch_latest()
                
                if new_items:
                    # Update Sliding Window
                    for item in new_items:
                        self.history.append(item)
                    
                    # Trim to keep only last 1000
                    if len(self.history) > TARGET_WINDOW_SIZE:
                        # Remove oldest
                        self.history = self.history[-TARGET_WINDOW_SIZE:]
                    
                    # 2. TRIGGER ANALYSIS IMMEDIATELY
                    # Since data changed, the "best salt" might have changed
                    self.analyze_window()

            except Exception as e:
                print(f"Worker Error {self.game_type}: {e}")

            # 3. Wait
            # Polling speed
            time.sleep(3 if self.game_type == "30s" else 5)

def start_salt_service():
    # Worker 1: 30 Seconds
    worker_30 = SaltCrackerWorker("30s", URL_30S, BOT_TOKEN, ADMIN_ID)
    worker_30.daemon = True 
    worker_30.start()

    # Worker 2: 1 Minute
    worker_1m = SaltCrackerWorker("1m", URL_1M, BOT_TOKEN, ADMIN_ID)
    worker_1m.daemon = True
    worker_1m.start()