import requests
import time
import logging
import json
import random

logger = logging.getLogger(__name__)

# --- COMMON API (Tiranga / RajaGames) ---
COMMON_URLS = {
    "30s": {
        "current": "https://draw.ar-lottery01.com/WinGo/WinGo_30S.json",
        "history": "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
    },
    "1m": {
        "current": "https://draw.ar-lottery01.com/WinGo/WinGo_1M.json",
        "history": "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
    }
}

# --- TRUSTWIN API (Attempting Web-Mode GET) ---
# We try to hit the endpoints that the website uses, which often don't require signatures.
TRUSTWIN_URLS = {
    "30s": {
        "current": "https://trustwin.vip/api/webapi/GetGameIssue?typeId=4&language=0",
        "history": "https://trustwin.vip/api/webapi/GetNoaverageEmerdList?typeId=4&pageSize=10&pageNo=1&language=0"
    },
    "1m": {
        "current": "https://trustwin.vip/api/webapi/GetGameIssue?typeId=1&language=0",
        "history": "https://trustwin.vip/api/webapi/GetNoaverageEmerdList?typeId=1&pageSize=10&pageNo=1&language=0"
    }
}

def get_headers(platform="Tiranga"):
    """
    Standard browser headers to avoid being blocked.
    """
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8"
    }

    if platform == "TrustWin":
        base_headers.update({
            "Referer": "https://trustwin.vip/",
            "Origin": "https://trustwin.vip",
            "Host": "trustwin.vip"
        })
    else:
        base_headers.update({
            "Referer": "https://www.92lottery.com/",
            "Origin": "https://www.92lottery.com"
        })
    return base_headers

def get_game_data(game_type="30s", platform="Tiranga"):
    clean_history = []
    current_period = None
    
    try:
        # --- 1. SETUP URLS & HEADERS ---
        if platform == "TrustWin":
            urls = TRUSTWIN_URLS["30s"] if game_type == "30s" else TRUSTWIN_URLS["1m"]
            headers = get_headers("TrustWin")
            # TrustWin often requires a fresh timestamp in the URL to prevent caching
            ts = int(time.time() * 1000)
            url_suffix = f"&random={ts}&timestamp={ts}" # Dummy params to mimic browser
        else:
            key = "30s" if game_type == "30s" else "1m"
            urls = COMMON_URLS[key]
            headers = get_headers("Tiranga")
            ts = int(time.time() * 1000)
            url_suffix = f"?ts={ts}"

        # --- 2. GET CURRENT PERIOD ---
        try:
            # We use GET for everything now to avoid the Signature issue
            curr_resp = requests.get(urls["current"] + url_suffix, headers=headers, timeout=5)
            curr_data = curr_resp.json()
            
            # Debugging TrustWin
            if platform == "TrustWin" and curr_resp.status_code != 200:
                print(f"DEBUG TRUSTWIN CURRENT: {curr_resp.status_code}")

            if isinstance(curr_data, dict):
                # Handle standard 'data' -> 'issueNumber' structure
                if 'data' in curr_data and isinstance(curr_data['data'], dict):
                    current_period = curr_data['data'].get('issueNumber')
                elif 'issueNumber' in curr_data:
                    current_period = curr_data.get('issueNumber')

        except Exception as e:
            logger.error(f"Error fetching current ({platform}): {e}")

        # --- 3. GET HISTORY ---
        try:
            hist_resp = requests.get(urls["history"] + url_suffix, headers=headers, timeout=5)
            hist_data = hist_resp.json()
            
            raw_list = hist_data.get('data', {}).get('list', [])
            
            for item in raw_list:
                period = str(item['issueNumber'])
                result_num = int(item['number'])
                outcome = "Small" if result_num <= 4 else "Big"
                clean_history.append({'p': period, 'r': result_num, 'o': outcome})
            
            clean_history.reverse()

        except Exception as e:
            logger.error(f"Error fetching history ({platform}): {e}")

        # --- 4. FALLBACK ---
        # If current period failed but history worked, calculate next period
        if not current_period and clean_history:
            try:
                last_issue = int(clean_history[-1]['p'])
                current_period = str(last_issue + 1)
            except: pass

        return str(current_period) if current_period else None, clean_history

    except Exception as e:
        logger.error(f"Critical API Error ({platform}): {e}")
        return None, []
