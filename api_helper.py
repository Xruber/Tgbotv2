import aiohttp
import time
import logging
import asyncio

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.92lottery.com/"
}

async def fetch_json(session, url, params=None):
    """Async helper to fetch JSON with timeout."""
    try:
        async with session.get(url, headers=HEADERS, params=params, timeout=5) as response:
            if response.status == 200:
                return await response.json()
    except Exception as e:
        logger.error(f"API Request Failed: {e}")
    return None

async def get_game_data(game_type="30s"):
    """
    Fetches Current Period and History Asynchronously.
    """
    type_urls = URLS.get(game_type, URLS["30s"])
    timestamp = int(time.time() * 1000)
    
    async with aiohttp.ClientSession() as session:
        # 1. Fetch History (Most Reliable)
        hist_data = await fetch_json(session, type_urls['history'], params={"ts": timestamp, "page": 1, "size": 10})
        
        if not hist_data:
            return None, []

        clean_history = []
        raw_list = hist_data.get('data', {}).get('list', [])
        
        for item in raw_list:
            period = str(item['issueNumber'])
            result_num = int(item['number'])
            outcome = "Small" if result_num <= 4 else "Big"
            clean_history.append({'p': period, 'r': result_num, 'o': outcome})
            
        if not clean_history:
            return None, []
            
        clean_history.reverse() # Oldest to Newest
        
        # 2. Calculate Current Period from History
        last_issue = int(clean_history[-1]['p'])
        current_period = str(last_issue + 1)

        return current_period, clean_history

async def check_result_exists(game_type, target_period):
    """
    Checks if result exists for period (Async).
    """
    _, history = await get_game_data(game_type)
    if not history: return False, None
    
    for item in history:
        if str(item['p']) == str(target_period):
            return True, item['o'] # Found result
            
    return False, None
