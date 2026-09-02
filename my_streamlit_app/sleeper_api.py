import requests
import streamlit as st
from datetime import datetime

def get_current_nfl_week() -> int:
    """Calcule automatiquement la semaine NFL courante basée sur la date actuelle."""
    today = datetime.now()
    # Début estimé de la saison régulière (premier jeudi de septembre)
    # Pour 2026, la semaine 1 démarre début septembre.
    # Ajuste l'année/mois de référence si besoin :
    season_start = datetime(today.year, 9, 3) 
    
    if today < season_start:
        return 1
    
    delta_days = (today - season_start).days
    current_week = (delta_days // 7) + 1
    
    # Borne entre 1 et 18
    return max(1, min(current_week, 18))


@st.cache_data(ttl=86400)  # Cache de 24h
def fetch_nfl_schedule(season_year="2026"):
    schedule_by_week = {}
    
    # Parcourt les 18 semaines de la saison régulière
    for week in range(1, 19):
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={season_year}&week={week}&seasontype=2"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                events = data.get("events", [])
                games = []
                for event in events:
                    competitors = event["competitions"][0]["competitors"]
                    home_team = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "home")
                    away_team = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "away")
                    
                    games.append({
                        "away": away_team,
                        "home": home_team,
                        "label": f"{away_team} @ {home_team}"
                    })
                schedule_by_week[week] = games
        except Exception:
            continue

    return schedule_by_week


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
