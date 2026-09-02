import streamlit as st

# --- INITIALISATION CONFIGURATION ---
from config import setup_page_config
setup_page_config()

# --- IMPORT MODULES, SIDEBAR ET TABS ---
from db import init_db, load_persisted_state, load_excluded_leagues_db
from helpers import get_league_format_badge, compute_all_data_and_opportunities
from sidebar import render_sidebar
from tabs import (
    render_group_a_tab,
    render_group_b_tab,
    render_radar_tab,
    render_waivers_tab,
    render_matchups_tab, 
    render_alerts_tab
)

# Initialisation de la BDD Turso
init_db()

# Chargement de la session state
if "trade_history" not in st.session_state:
    t_hist, b_owners, b_targets = load_persisted_state()
    st.session_state["trade_history"] = t_hist
    st.session_state["blacklisted_owners"] = b_owners
    st.session_state["blacklisted_targets"] = b_targets

if st.session_state.get("db_warning"):
    st.error(f"⚠️ **Alerte BDD Turso :** {st.session_state['db_warning']}")

if "excluded_leagues" not in st.session_state or not st.session_state["excluded_leagues"]:
    st.session_state["excluded_leagues"] = load_excluded_leagues_db()

accepted_trades = [t for t in st.session_state["trade_history"] if t["status"] == "Accepté"]
accepted_trades_tuple = tuple(
    (t["league"], t.get("target_id"), t["target_name"], tuple(t["offered_names"]))
    for t in accepted_trades
)

# Récupération de l'ID depuis la session state si déjà saisi
user_id = st.session_state.get("user_id_input", "742374956750540800")
season_year = st.session_state.get("season_year", "2026")
threshold_group_a = st.session_state.get("threshold_group_a", 3)

# Calcul principal avec Spinner
with st.spinner("Analyse et calcul des opportunités..."):
    (
        df_rosters,
        group_a,
        group_b,
        target_opportunities,
        leagues,
        league_size_map,
        league_reqs_map,
        league_rosters_map,
        user_full_roster_objects,
        draft_completed_leagues,
    ) = compute_all_data_and_opportunities(
        user_id, season_year, threshold_group_a, accepted_trades_tuple
    )

league_badge_map = {
    l["name"]: get_league_format_badge(l.get("roster_positions"), l.get("settings", {}))
    for l in leagues
} if leagues else {}

all_league_names = [l["name"] for l in leagues] if leagues else []

# Rendu complet et unique de la Sidebar
(
    user_id_input, 
    season_year, 
    threshold_group_a, 
    filter_upgrade_pure, 
    filter_trade_urgent
) = render_sidebar(all_league_names, league_badge_map, group_b)

if df_rosters is None:
    st.warning("Aucun roster trouvé pour cet utilisateur/saison.")
    st.stop()

excluded_leagues_input = st.session_state["excluded_leagues"]

pending_trades = [t for t in st.session_state["trade_history"] if t["status"] == "En cours"]
pending_target_pairs = set((t["target_name"], t["league"]) for t in pending_trades)
pending_offered_pairs = set((p_name, t["league"]) for t in pending_trades for p_name in t["offered_names"])

# --- NAVIGATION ONGLETS ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⭐ Groupe A (Targets)", 
    "🔄 Groupe B (A Trader)", 
    "🎯 Radar de Trade", 
    "📥 Waivers",
    "🏈 Matchups NFL",
    " Alerte Inactifs"
])

with tab1:
    render_group_a_tab(group_a, threshold_group_a, league_badge_map, pending_target_pairs, pending_offered_pairs)

with tab2:
    render_group_b_tab(group_b, threshold_group_a, league_badge_map, pending_target_pairs, pending_offered_pairs)

with tab3:
    render_radar_tab(
        leagues, draft_completed_leagues, excluded_leagues_input, league_badge_map,
        pending_trades, target_opportunities, pending_target_pairs,
        filter_upgrade_pure, filter_trade_urgent
    )

with tab4:
    render_waivers_tab(
        leagues, draft_completed_leagues, 
        league_rosters_map, user_full_roster_objects, league_size_map
    )

with tab5:
    render_matchups_tab(group_a, group_b, threshold_group_a, season_year)

with tab6:
    render_alerts_tab(leagues_data, players_dict)
