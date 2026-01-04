import requests
import time
import logging

logger = logging.getLogger(__name__)

# Game API Endpoints
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
    """Standard headers to mimic a browser."""
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Referer": "https://www.92lottery.com/",
        "Origin": "https://www.92lottery.com"
    }

def get_game_data(game_type="30s"):
    """
    Fetches Current Period and History.
    Includes Fallback Logic if 'Current' API returns empty.
    """
    type_key = "1m" if game_type == "1m" else "30s"
    urls = URLS[type_key]
    timestamp = int(time.time() * 1000)
    
    current_period = None
    clean_history = []
    
    try:
        # --- 1. Try to get Current Period directly ---
        try:
            curr_resp = requests.get(f"{urls['current']}?ts={timestamp}", headers=get_headers(), timeout=5)
            curr_data = curr_resp.json()
            
            # Check deep nested 'data' -> 'issueNumber'
            if isinstance(curr_data, dict):
                if 'data' in curr_data and isinstance(curr_data['data'], dict):
                    current_period = curr_data['data'].get('issueNumber')
                if not current_period:
                    current_period = curr_data.get('issueNumber')
        except:
            pass # Continue to history fallback

        # --- 2. Get History (Critical) ---
        hist_resp = requests.get(f"{urls['history']}?ts={timestamp}&page=1&size=10", headers=get_headers(), timeout=5)
        hist_data = hist_resp.json()
        raw_list = hist_data.get('data', {}).get('list', [])
        
        # Build History List
        for item in raw_list:
            period = str(item['issueNumber'])
            result_num = int(item['number'])
            outcome = "Small" if result_num <= 4 else "Big"
            clean_history.append({'p': period, 'r': result_num, 'o': outcome})
            
        clean_history.reverse() # Oldest to Newest
        
        # --- 3. FALLBACK: Calculate Period from History ---
        # If the main API failed to give us the current period, we calculate it:
        # Current Period = (Last Result Period) + 1
        if not current_period and clean_history:
            last_issue = int(clean_history[-1]['p'])
            current_period = str(last_issue + 1)

        return str(current_period) if current_period else None, clean_history

    except Exception as e:
        logger.error(f"API Error ({game_type}): {e}")
        return None, []