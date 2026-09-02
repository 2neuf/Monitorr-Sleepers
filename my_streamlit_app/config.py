
import streamlit as st

# --- CONFIGURATION STREAMLIT ---
def setup_page_config():
    st.set_page_config(
        page_title="Empire Trade Radar",
        page_icon="🏈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

# --- SECRETS BDD TURSO ---
TURSO_DATABASE_URL = st.secrets.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")

# --- CALENDRIER REEL NFL (Saison Régulière) ---
def get_nfl_schedule_2026():
    return {
        1: [
            {"away": "NE", "home": "SEA", "label": "NE @ SEA"},
            {"away": "SF", "home": "LAR", "label": "SF @ LAR"},
            {"away": "CHI", "home": "CAR", "label": "CHI @ CAR"},
            {"away": "TB", "home": "CIN", "label": "TB @ CIN"},
            {"away": "NO", "home": "DET", "label": "NO @ DET"},
            {"away": "BUF", "home": "HOU", "label": "BUF @ HOU"},
            {"away": "BAL", "home": "IND", "label": "BAL @ IND"},
            {"away": "CLE", "home": "JAX", "label": "CLE @ JAX"},
            {"away": "ATL", "home": "PIT", "label": "ATL @ PIT"},
            {"away": "NYJ", "home": "TEN", "label": "NYJ @ TEN"},
            {"away": "ARI", "home": "LAC", "label": "ARI @ LAC"},
            {"away": "MIA", "home": "LV", "label": "MIA @ LV"},
            {"away": "GB", "home": "MIN", "label": "GB @ MIN"},
            {"away": "WAS", "home": "PHI", "label": "WAS @ PHI"},
            {"away": "DAL", "home": "NYG", "label": "DAL @ NYG"},
            {"away": "DEN", "home": "KC", "label": "DEN @ KC"},
        ],
        2: [
            {"away": "KC", "home": "BAL", "label": "KC @ BAL"},
            {"away": "GB", "home": "PHI", "label": "GB @ PHI"},
            {"away": "ARI", "home": "BUF", "label": "ARI @ BUF"},
            {"away": "NYJ", "home": "SF", "label": "NYJ @ SF"},
        ]
    }
