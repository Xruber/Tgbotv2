import threading
import time
import requests
import hashlib
import itertools
import asyncio
from telegram import Bot
from config import ADMIN_ID, BOT_TOKEN

# --- CONFIGURATION ---
TARGET_WINDOW_SIZE = 1000  # Keep history of 1000
ANALYSIS_SUBSET_SIZE = 100 # Analyze last 100 for live speed (prevents lag)
MAX_COMBINATION_LENGTH = 2 # Length 2 is optimal for speed

# GLOBAL STORAGE
LATEST_RESULTS = {
    "30s": {
        "salt": "Initializing...", 
        "acc": 0.0, 
        "max_streak": 0,
        "is_safe": False,
        "total_scanned": 0,
        "current_period": "Waiting...",
        "last_update": "..."
    },
    "1m": {
        "salt": "Initializing...", 
        "acc": 0.0, 
        "max_streak": 0,
        "is_safe": False,
        "total_scanned": 0,
        "current_period": "Waiting...",
        "last_update": "..."
    }
}

# URLs
URL_30S = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
URL_1M = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

# Wordlist
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
        self.history = [] 
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
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Referer": "https://www.92lottery.com/",
                "Origin": "https://www.92lottery.com"
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
            # Return reversed (Oldest -> Newest)
            return new_items[::-1] 
        except Exception as e:
            return []

    def analyze_window(self):
        """Finds best salt with PRIORITY on Max Streak < 5."""
        total_history = len(self.history)
        if total_history < 10:
            self.update_status("Gathering Data...", 0, 0, False, total_history)
            return

        # Optimization: Analyze subset for speed
        if total_history > ANALYSIS_SUBSET_SIZE:
            analysis_set = self.history[-ANALYSIS_SUBSET_SIZE:]
        else:
            analysis_set = self.history

        best_metric = (-1, -1) # Tuple: (is_safe, accuracy)
        best_salt = "None"
        best_stats = (0, 0) # (max_streak, is_safe)
        
        # Brute Force
        for length in range(1, MAX_COMBINATION_LENGTH + 1):
            combos = itertools.product(SALTS, repeat=length)
            for combo in combos:
                salt_candidate = "".join(combo)
                
                correct = 0
                curr_loss_streak = 0
                max_loss_streak = 0
                
                for item in analysis_set:
                    pred = self.get_prediction(item['p'], salt_candidate)
                    if pred == item['r']:
                        correct += 1
                        curr_loss_streak = 0
                    else:
                        curr_loss_streak += 1
                        if curr_loss_streak > max_loss_streak:
                            max_loss_streak = curr_loss_streak
                
                accuracy = correct / len(analysis_set)
                
                # === HERE IS THE LEVEL 5 CHECK ===
                # If max_loss_streak is less than 5, it is considered SAFE (1)
                # If it is 5 or more, it is RISKY (0)
                is_safe = 1 if max_loss_streak < 5 else 0 
                
                # We sort by Safety First (1 vs 0), then by Accuracy
                metric = (is_safe, accuracy)
                
                if metric > best_metric:
                    best_metric = metric
                    best_salt = salt_candidate
                    best_stats = (max_loss_streak, bool(is_safe))

        # Update Global
        final_acc = best_metric[1] * 100 if best_metric[1] != -1 else 0
        self.update_status(best_salt, final_acc, best_stats[0], best_stats[1], total_history)

    def update_status(self, salt, acc, max_streak, is_safe, count):
        latest_period = self.history[-1]['p'] if self.history else "Waiting..."
        LATEST_RESULTS[self.game_type] = {
            "salt": salt,
            "acc": round(acc, 2),
            "max_streak": max_streak,
            "is_safe": is_safe,
            "total_scanned": count,
            "current_period": latest_period,
            "last_update": time.strftime("%H:%M:%S")
        }

    def run(self):
        print(f"✅ Live Service Started: Wingo {self.game_type}")
        while self.running:
            try:
                # 1. Fetch
                new_items = self.fetch_latest()
                if new_items:
                    for item in new_items:
                        self.history.append(item)
                    
                    if len(self.history) > TARGET_WINDOW_SIZE:
                        self.history = self.history[-TARGET_WINDOW_SIZE:]
                    
                    self.analyze_window()
                
                elif len(self.history) > 0 and LATEST_RESULTS[self.game_type]['salt'] == "Initializing...":
                     self.analyze_window()

            except Exception as e:
                print(f"Worker Error {self.game_type}: {e}")

            time.sleep(3 if self.game_type == "30s" else 5)

def start_salt_service():
    worker_30 = SaltCrackerWorker("30s", URL_30S, BOT_TOKEN, ADMIN_ID)
    worker_30.daemon = True 
    worker_30.start()

    worker_1m = SaltCrackerWorker("1m", URL_1M, BOT_TOKEN, ADMIN_ID)
    worker_1m.daemon = True
    worker_1m.start()
