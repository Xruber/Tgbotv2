import requests
import time
import logging

# Configuration
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.92lottery.com/"
}

URLS = {
    "30s": "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json",
    "1m": "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
}

def get_game_data(game_type="30s"):
    """
    Fetches the API data.
    Returns: (Current_Period_String, History_List)
    """
    url = URLS.get(game_type, URLS["30s"])
    timestamp = int(time.time() * 1000)
    
    try:
        response = requests.get(f"{url}?ts={timestamp}&page=1&size=10", headers=HEADERS, timeout=5)
        data = response.json()
        
        raw_list = data.get('data', {}).get('list', [])
        clean_history = []
        
        for item in raw_list:
            period = str(item['issueNumber'])
            number = int(item['number'])
            outcome = "Big" if number >= 5 else "Small"
            clean_history.append({'p': period, 'r': number, 'o': outcome})
            
        if not clean_history:
            return None, []
            
        # Sort: Oldest -> Newest (History[-1] is the most recent result)
        clean_history.reverse()
        
        # Calculate Current Period (Last Result + 1)
        last_period = int(clean_history[-1]['p'])
        current_period = str(last_period + 1)
        
        return current_period, clean_history

    except Exception as e:
        print(f"API Error: {e}")
        return None, []

def check_result_exists(game_type, target_period):
    """
    Checks if the result for a specific period has been published.
    Returns: (True/False, Outcome)
    """
    current, history = get_game_data(game_type)
    if not history: return False, None
    
    for item in history:
        if str(item['p']) == str(target_period):
            return True, item['o']
            
    return False, None
