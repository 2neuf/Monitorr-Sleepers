
import streamlit as st
import requests

@st.cache_data(ttl=86400)
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else {}

@st.cache_data(ttl=3600)
def fetch_user_leagues(user_id, year):
    url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

@st.cache_data(ttl=3600)
def fetch_league_rosters(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

@st.cache_data(ttl=3600)
def fetch_league_users(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    res = requests.get(url)
    if res.status_code == 200:
        return {u["user_id"]: u.get("display_name", u.get("username", "Inconnu")) for u in res.json()}
    return {}

@st.cache_data(ttl=3600)
def fetch_league_draft_info(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/drafts"
    res = requests.get(url)
    roster_to_slot = {}
    completed_seasons = set()
    is_upcoming_draft_done = True
    
    if res.status_code == 200:
        drafts = res.json()
        for d in drafts:
            status = d.get("status")
            if status == "complete":
                completed_seasons.add(str(d.get("season")))
            else:
                is_upcoming_draft_done = False

            draft_id = d.get("draft_id")
            if draft_id:
                picks_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
                if picks_res.status_code == 200:
                    for p in picks_res.json():
                        if p.get("round") == 1:
                            roster_to_slot[p.get("roster_id")] = p.get("draft_slot")
                            
    return roster_to_slot, completed_seasons, is_upcoming_draft_done

@st.cache_data(ttl=3600)
def fetch_league_traded_picks(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/traded_picks"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

@st.cache_data(ttl=3600)
def fetch_trending_players(type="add", lookback_hours=24, limit=25):
    """Récupère la liste des joueurs les plus ajoutés sur Sleeper."""
    url = f"https://api.sleeper.app/v1/players/nfl/trending/{type}?lookback_hours={lookback_hours}&limit={limit}"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []
