import threading
import time
import requests
import hashlib
import itertools
import asyncio
from telegram import Bot
from config import ADMIN_ID, BOT_TOKEN

# --- CONFIGURATION ---
TARGET_BATCH_SIZE = 1000  # Analyze exactly 1000 periods
MAX_COMBINATION_LENGTH = 3

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
            return new_items
        except Exception as e:
            return []

    def analyze_batch(self):
        print(f"[{self.game_type}] 🧠 Analyzing batch of {len(self.history)} rounds...")
        best_score = -1
        best_salt = "None"
        
        # Brute Force
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

        # Send Report
        self.notify_admin(best_salt, best_score, len(self.history))
        
        # Reset History for next batch
        self.history = []
        print(f"[{self.game_type}] ✅ Report sent. Memory cleared for new batch.")

    def notify_admin(self, salt, wins, total):
        accuracy = (wins / total) * 100
        msg = (
            f"📊 **BATCH ANALYSIS COMPLETE** 📊\n\n"
            f"🎮 Game: **Wingo {self.game_type}**\n"
            f"📅 Total Periods: **{total}**\n"
            f"🏆 Best Salt Found: `{salt}`\n"
            f"✅ Wins: **{wins}**\n"
            f"🔥 Accuracy: **{accuracy:.2f}%**\n\n"
            f"♻️ _Memory cleared. Starting next 1000 rounds..._"
        )
        asyncio.run(self.bot.send_message(chat_id=self.admin_id, text=msg, parse_mode="Markdown"))

    def run(self):
        print(f"✅ Background Service Started: Wingo {self.game_type}")
        while self.running:
            # 1. Fetch
            new_items = self.fetch_latest()
            if new_items:
                # Add new items
                for item in new_items:
                    if not any(x['p'] == item['p'] for x in self.history):
                         self.history.append(item)
                
                self.history.sort(key=lambda x: x['p'])
                
                # Check Batch Completion
                if len(self.history) >= TARGET_BATCH_SIZE:
                    # Trim to exactly 1000 just in case
                    self.history = self.history[:TARGET_BATCH_SIZE]
                    self.analyze_batch()

            # 2. Wait
            # Wingo 30s updates fast, 1m updates slow
            time.sleep(5 if self.game_type == "30s" else 10)

def start_salt_service():
    # Worker 1: 30 Seconds
    worker_30 = SaltCrackerWorker("30s", URL_30S, BOT_TOKEN, ADMIN_ID)
    worker_30.daemon = True 
    worker_30.start()

    # Worker 2: 1 Minute
    worker_1m = SaltCrackerWorker("1m", URL_1M, BOT_TOKEN, ADMIN_ID)
    worker_1m.daemon = True
    worker_1m.start()