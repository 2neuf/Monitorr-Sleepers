import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# Configuration de la page Streamlit pour mobile
st.set_page_config(page_title="Sleeper Roster Manager", layout="wide")

# Initialisation de l'historique des trades dans la session
if "trade_history" not in st.session_state:
    st.session_state["trade_history"] = []

st.title("🏈 Sleeper Roster Manager")
st.caption("Consolide tes rosters et repère tes meilleures opportunités de trade.")

# Sidebar pour les paramètres
st.sidebar.header("Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

# Priorité de tri par poste
POS_ORDER = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "K": 5, "DEF": 6}

# 1. Base de données globale des joueurs Sleeper
@st.cache_data(ttl=86400)
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return {}

# 2. Chargement des membres d'une ligue (Owner ID -> Pseudo)
@st.cache_data(ttl=3600)
def fetch_league_users(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    try:
        response = requests.get(url).json()
        users_map = {}
        for u in response:
            users_map[u["user_id"]] = u.get("display_name") or u.get("username") or "Anonyme"
        return users_map
    except:
        return {}

# 3. Chargement des ligues et rosters d'un utilisateur
@st.cache_data(ttl=600)
def fetch_user_data(user_id, year):
    leagues_url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}"
    leagues = requests.get(leagues_url).json()
    
    user_rosters = []
    league_details = {}

    for league in leagues:
        league_id = league["league_id"]
        league_details[league_id] = league["name"]
        
        rosters_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
        rosters = requests.get(rosters_url).json()
        
        for roster in rosters:
            if roster.get("owner_id") == user_id:
                players = roster.get("players") or []
                for p_id in players:
                    user_rosters.append({
                        "player_id": p_id,
                        "league_id": league_id,
                        "league_name": league["name"]
                    })
    
    return user_rosters, league_details, leagues

# Chargement des données
with st.spinner("Chargement des données Sleeper..."):
    all_players = load_sleeper_players()
    roster_data, league_map, leagues = fetch_user_data(user_id_input, season_year)

if not roster_data:
    st.warning("Aucun roster trouvé pour cet utilisateur/saison.")
    st.stop()

# Transformation des données
df_rosters = pd.DataFrame(roster_data)

def get_player_info(p_id):
    p_info = all_players.get(str(p_id), {})
    name = p_info.get("full_name", f"Joueur inconnu ({p_id})")
    pos = p_info.get("position", "N/A")
    team = p_info.get("team", "N/A")
    return name, pos, team

df_rosters[["player_name", "position", "team"]] = df_rosters["player_id"].apply(
    lambda x: pd.Series(get_player_info(x))
)

# Calcul de l'exposition (Exposure)
exposure = df_rosters.groupby(["player_id", "player_name", "position", "team"]).agg(
    shares=("league_id", "count"),
    leagues=("league_name", lambda x: list(x))
).reset_index()

exposure["pos_rank"] = exposure["position"].map(lambda x: POS_ORDER.get(x, 99))

group_a = exposure[exposure["shares"] >= threshold_group_a].sort_values(by=["pos_rank", "shares"], ascending=[True, False])
group_b = exposure[exposure["shares"] < threshold_group_a].sort_values(by=["pos_rank", "shares"], ascending=[True, False])

# --- INTERFACE STREAMLIT ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

# --- ONGLET 1 : GROUPE A ---
with tab1:
    st.subheader(f"Joueurs clés (≥ {threshold_group_a} parts)")
    col_filter_a, _ = st.columns([1, 2])
    with col_filter_a:
        pos_filter_a = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_a")
    
    filtered_a = group_a if pos_filter_a == "Tous" else group_a[group_a["position"] == pos_filter_a]
    st.write(f"Total : **{len(filtered_a)}** joueurs")
    
    for _, row in filtered_a.iterrows():
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — **{row['shares']} parts**"):
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

# --- ONGLET 2 : GROUPE B ---
with tab2:
    st.subheader(f"Joueurs secondaires (< {threshold_group_a} parts)")
    col_filter_b, _ = st.columns([1, 2])
    with col_filter_b:
        pos_filter_b = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_b")
        
    filtered_b = group_b if pos_filter_b == "Tous" else group_b[group_b["position"] == pos_filter_b]
    st.write(f"Total : **{len(filtered_b)}** joueurs")
    
    for _, row in filtered_b.iterrows():
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — **{row['shares']} part(s)**"):
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

# --- ONGLET 3 : RADAR DE TRADE & HISTORIQUE ---
with tab3:
    st.subheader("💡 Opportunités de Trade Détectées")
    
    group_a_ids = set(group_a["player_id"])
    group_b_ids = set(group_b["player_id"])
    
    target_opportunities = []
    
    with st.spinner("Analyse des rosters adverses..."):
        for league in leagues:
            l_id = league["league_id"]
            l_name = league["name"]
            
            my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))]
            if my_b_in_league.empty:
                continue
            
            league_users = fetch_league_users(l_id)
            rosters_url = f"https://api.sleeper.app/v1/league/{l_id}/rosters"
            rosters = requests.get(rosters_url).json()
            
            for r in rosters:
                if r.get("owner_id") != user_id_input:
                    r_players = set(r.get("players") or [])
                    targets_held = r_players.intersection(group_a_ids)
                    
                    if targets_held:
                        owner_pseudo = league_users.get(r.get("owner_id"), "Propriétaire Inconnu")
                        
                        for target_id in targets_held:
                            t_name, t_pos, t_team = get_player_info(target_id)
                            
                            b_options = [
                                f"{my_row['player_name']} ({my_row['position']} - {my_row['team']})"
                                for _, my_row in my_b_in_league.iterrows()
                            ]
                            
                            target_opportunities.append({
                                "target_name": t_name,
                                "target_pos": t_pos,
                                "target_team": t_team,
                                "league_name": l_name,
                                "owner_pseudo": owner_pseudo,
                                "b_options": b_options
                            })

    if target_opportunities:
        # --- FILTRES DE L'ONGLET 3 ---
        col_f1, col_f2 = st.columns(2)
        
        all_leagues = ["Toutes"] + sorted(list(set(o["league_name"] for o in target_opportunities)))
        all_positions = ["Tous", "QB", "RB", "WR", "TE"]
        
        with col_f1:
            selected_league = st.selectbox("Filtrer par ligue", all_leagues, key="trade_league_filter")
        with col_f2:
            selected_pos = st.selectbox("Filtrer par poste ciblé", all_positions, key="trade_pos_filter")
            
        # Filtrage de la liste des opportunités
        filtered_opps = target_opportunities
        if selected_league != "Toutes":
            filtered_opps = [o for o in filtered_opps if o["league_name"] == selected_league]
        if selected_pos != "Tous":
            filtered_opps = [o for o in filtered_opps if o["target_pos"] == selected_pos]
            
        st.write(f"**{len(filtered_opps)}** opportunité(s) affichée(s) :")
        
        # Affichage des opportunités
        for idx, opp in enumerate(filtered_opps):
            header_text = f"🎯 **{opp['target_name']}** ({opp['target_pos']}) | Ligue : *{opp['league_name']}* | Owner : **@{opp['owner_pseudo']}**"
            
            with st.expander(header_text):
                st.markdown("👉 **Sélectionne le ou les joueurs à inclure dans ton offre :**")
                
                # Formulaire de sélection unique par opportunité
                key_select = f"select_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{idx}"
                key_btn = f"btn_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{idx}"
                
                selected_offers = st.multiselect(
                    "Tes joueurs du Groupe B disponibles :",
                    options=opp["b_options"],
                    default=[],
                    key=key_select
                )
                
                if st.button("📌 Enregistrer cette proposition", key=key_btn):
                    if selected_offers:
                        trade_entry = {
                            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "league": opp["league_name"],
                            "owner": opp["owner_pseudo"],
                            "target": f"{opp['target_name']} ({opp['target_pos']})",
                            "offered": ", ".join(selected_offers)
                        }
                        st.session_state["trade_history"].append(trade_entry)
                        st.success(f"Offre pour {opp['target_name']} enregistrée dans l'historique !")
                    else:
                        st.warning("Veuillez sélectionner au moins un joueur à offrir.")

    else:
        st.info("Aucune opportunité directe trouvée entre tes joueurs du Groupe B et les cibles du Groupe A.")

    # --- HISTORIQUE DES TRADES ---
    st.markdown("---")
    st.subheader("📋 Historique des Propositions Enregistrées")
    
    if st.session_state["trade_history"]:
        df_history = pd.DataFrame(st.session_state["trade_history"])
        st.dataframe(
            df_history.rename(columns={
                "date": "Date",
                "league": "Ligue",
                "owner": "Adversaire",
                "target": "Joueur Cible",
                "offered": "Joueur(s) Offert(s)"
            }),
            use_container_width=True
        )
        
        if st.button("🗑️ Effacer l'historique"):
            st.session_state["trade_history"] = []
            st.rerun()
    else:
        st.caption("Aucune proposition enregistrée pour le moment. Sélectionne des joueurs ci-dessus pour construire tes offres.")
