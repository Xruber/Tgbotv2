import requests
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K)",
    "Referer": "https://www.92lottery.com/"
}

URLS = {
    "30s": "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json",
    "1m": "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
}

def get_game_data(game_type="30s"):
    """Fetch current period and history."""
    url = URLS.get(game_type, URLS["30s"])
    try:
        ts = int(time.time() * 1000)
        resp = requests.get(f"{url}?ts={ts}&page=1&size=10", headers=HEADERS, timeout=5).json()
        
        raw_list = resp.get('data', {}).get('list', [])
        history = []
        for item in raw_list:
            p = str(item['issueNumber'])
            res = int(item['number'])
            out = "Big" if res >= 5 else "Small"
            history.append({'p': p, 'r': res, 'o': out})
            
        history.reverse() # Oldest first
        
        if not history: return None, []
        
        # Calculate Next Period (Current)
        last_p = int(history[-1]['p'])
        current_p = str(last_p + 1)
        
        return current_p, history
    except Exception as e:
        print(f"API Error: {e}")
        return None, []

def check_result_exists(game_type, period_to_check):
    """
    CRITICAL FIX: Checks if the result for 'period_to_check' is actually published.
    """
    _, history = get_game_data(game_type)
    for item in history:
        if str(item['p']) == str(period_to_check):
            return True, item['o'] # Result found, return Outcome
    return False, None
