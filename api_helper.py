import requests
import time
import logging
import json

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

# --- TRUSTWIN API ---
TRUSTWIN_URLS = {
    "history": "https://trustwin.vip/apifolder/api/webapi/GetNoaverageEmerdList",
    "current": "https://trustwin.vip/apifolder/api/webapi/GetGameIssue"
}

# NOTE: These payloads use STATIC timestamps/signatures provided by you.
# If the server checks for expiration, these will eventually fail.
TRUSTWIN_PAYLOADS = {
    "30s_history": {
        "pageSize": 10, "pageNo": 1, "typeId": 4, "language": 0,
        "random": "bef52140a1c54a0f9bbec72fc3e19e11",
        "signature": "9F482656323FFA33A4CFC7A1F070D8DD",
        "timestamp": 1768123338
    },
    "30s_current": {
        "typeId": 4, "language": 0,
        "random": "a97208c116114d31abf5281a889225b7",
        "signature": "717C6DBD19843E3C483D326200289064",
        "timestamp": 1768123399
    },
    "1m_history": {
        "pageSize": 10, "pageNo": 1, "typeId": 1, "language": 0,
        "random": "1a0c0c3d7f89488884c028a851f83dff",
        "signature": "E877C4F408A568AC5B43E0A303431F2A",
        "timestamp": 1768123442
    },
    "1m_current": {
        "typeId": 1, "language": 0,
        "random": "0c70a6eb04364aa48ca12d843561ce35",
        "signature": "94E47E55B4C212697D81FDDF4EB856F7",
        "timestamp": 1768123442
    }
}

def get_headers(platform="Tiranga"):
    """
    Returns headers specific to the platform.
    TrustWin blocks requests if the Origin is wrong.
    """
    if platform == "TrustWin":
        return {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": "https://trustwin.vip/",
            "Origin": "https://trustwin.vip",
            "Content-Type": "application/json;charset=UTF-8"
        }
    else:
        # Default for Tiranga/Raja
        return {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": "https://www.92lottery.com/",
            "Origin": "https://www.92lottery.com",
            "Content-Type": "application/json;charset=UTF-8"
        }

def get_game_data(game_type="30s", platform="Tiranga"):
    clean_history = []
    current_period = None
    
    try:
        if platform == "TrustWin":
            # --- TRUSTWIN (POST) ---
            headers = get_headers("TrustWin")
            
            # 1. Get Current Period
            c_key = "30s_current" if game_type == "30s" else "1m_current"
            try:
                c_resp = requests.post(
                    TRUSTWIN_URLS["current"], 
                    json=TRUSTWIN_PAYLOADS[c_key], 
                    headers=headers, 
                    timeout=5
                )
                c_data = c_resp.json()
                
                # Debug Print to see what server says
                if c_resp.status_code != 200:
                    print(f"DEBUG TRUSTWIN CURRENT: {c_resp.status_code} - {c_resp.text}")

                if 'data' in c_data and isinstance(c_data['data'], dict):
                    current_period = c_data['data'].get('issueNumber')
            except Exception as e:
                logger.error(f"TrustWin Current Error: {e}")

            # 2. Get History
            h_key = "30s_history" if game_type == "30s" else "1m_history"
            try:
                h_resp = requests.post(
                    TRUSTWIN_URLS["history"], 
                    json=TRUSTWIN_PAYLOADS[h_key], 
                    headers=headers, 
                    timeout=5
                )
                h_data = h_resp.json()
                
                # Debug Print
                if h_resp.status_code != 200:
                    print(f"DEBUG TRUSTWIN HISTORY: {h_resp.status_code} - {h_resp.text}")

                raw_list = h_data.get('data', {}).get('list', [])
                
                for item in raw_list:
                    period = str(item['issueNumber'])
                    result_num = int(item['number'])
                    outcome = "Small" if result_num <= 4 else "Big"
                    clean_history.append({'p': period, 'r': result_num, 'o': outcome})
                
                clean_history.reverse()
            except Exception as e:
                logger.error(f"TrustWin History Error: {e}")

        else:
            # --- TIRANGA / RAJAGAMES (GET) ---
            headers = get_headers("Tiranga")
            type_key = "1m" if game_type == "1m" else "30s"
            urls = COMMON_URLS[type_key]
            timestamp = int(time.time() * 1000)
            
            # 1. Current
            try:
                curr_resp = requests.get(f"{urls['current']}?ts={timestamp}", headers=headers, timeout=5)
                curr_data = curr_resp.json()
                if isinstance(curr_data, dict):
                    if 'data' in curr_data and isinstance(curr_data['data'], dict):
                        current_period = curr_data['data'].get('issueNumber')
                    if not current_period:
                        current_period = curr_data.get('issueNumber')
            except: pass

            # 2. History
            hist_resp = requests.get(f"{urls['history']}?ts={timestamp}&page=1&size=10", headers=headers, timeout=5)
            hist_data = hist_resp.json()
            raw_list = hist_data.get('data', {}).get('list', [])
            
            for item in raw_list:
                period = str(item['issueNumber'])
                result_num = int(item['number'])
                outcome = "Small" if result_num <= 4 else "Big"
                clean_history.append({'p': period, 'r': result_num, 'o': outcome})
            
            clean_history.reverse()

        # --- FALLBACK CALCULATION ---
        if not current_period and clean_history:
            last_issue = int(clean_history[-1]['p'])
            current_period = str(last_issue + 1)

        return str(current_period) if current_period else None, clean_history

    except Exception as e:
        logger.error(f"API Error ({platform} {game_type}): {e}")
        return None, []
