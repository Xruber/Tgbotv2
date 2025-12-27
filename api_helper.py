import requests
import time
import logging

# Logger
logger = logging.getLogger(__name__)

# API Endpoints
URLS = {
    "30s": {
        "current": "https://draw.ar-lottery01.com/WinGo/WinGo_30S.json",
        "history": "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
    },
    "1m": {
        "current": "https://draw.ar-lottery01.com/WinGo/WinGo_1M.json",
        "history": "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
    }
}

def get_headers():
    """Fake headers to look like a real browser."""
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Referer": "https://www.92lottery.com/",
        "Origin": "https://www.92lottery.com"
    }

def get_game_data(game_type="30s"):
    """
    Fetches Current Period and Last 10 History.
    Returns: (current_period_str, history_list)
    """
    type_key = "1m" if game_type == "1m" else "30s"
    urls = URLS[type_key]
    timestamp = int(time.time() * 1000)
    
    try:
        # 1. Get Current Period
        curr_resp = requests.get(f"{urls['current']}?ts={timestamp}", headers=get_headers(), timeout=5)
        curr_data = curr_resp.json()
        # Fallback for different API structures (some use 'issueNumber', some 'period')
        current_period = str(curr_data.get('data', {}).get('issueNumber') or curr_data.get('issueNumber'))

        # 2. Get History (Last 10)
        hist_resp = requests.get(f"{urls['history']}?ts={timestamp}&page=1&size=10", headers=get_headers(), timeout=5)
        hist_data = hist_resp.json()
        raw_list = hist_data.get('data', {}).get('list', [])
        
        # Format history: [{'p': '202...123', 'r': 5, 'o': 'Big'}]
        clean_history = []
        for item in raw_list:
            period = str(item['issueNumber'])
            result_num = int(item['number'])
            outcome = "Small" if result_num <= 4 else "Big"
            clean_history.append({'p': period, 'r': result_num, 'o': outcome})
            
        # Sort: Oldest to Newest for pattern analysis
        clean_history.reverse()
        
        return current_period, clean_history

    except Exception as e:
        logger.error(f"API Error ({game_type}): {e}")
        return None, []