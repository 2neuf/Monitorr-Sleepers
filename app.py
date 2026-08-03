import streamlit as st
import requests
import pandas as pd

# Configuration de la page Streamlit pour mobile
st.set_page_config(page_title="Sleeper Roster Manager", layout="wide")

st.title("🏈 Sleeper Roster Manager")
st.caption("Consolide tes rosters et repère tes meilleures opportunités de trade.")

# Sidebar pour les paramètres
st.sidebar.header("Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

# 1. Chargement de la base de données globale des joueurs Sleeper (Mise en cache)
@st.cache_data(ttl=86400)  # Rechargé 1 fois par jour
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return {}

# 2. Chargement des ligues et rosters d'un utilisateur
@st.cache_data(ttl=600)  # Rechargé toutes les 10 min
def fetch_user_data(user_id, year):
    # Récupérer les ligues
    leagues_url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}"
    leagues = requests.get(leagues_url).json()
    
    user_rosters = []
    league_details = {}

    for league in leagues:
        league_id = league["league_id"]
        league_details[league_id] = league["name"]
        
        # Récupérer les rosters de la ligue
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

# Exécution du chargement avec indicateur
with st.spinner("Chargement des données Sleeper..."):
    all_players = load_sleeper_players()
    roster_data, league_map, leagues = fetch_user_data(user_id_input, season_year)

if not roster_data:
    st.warning("Aucun roster trouvé pour cet utilisateur/saison.")
    st.stop()

# Transformation des données en DataFrame Pandas
df_rosters = pd.DataFrame(roster_data)

# Associer le nom et le poste du joueur
def get_player_info(p_id):
    p_info = all_players.get(str(p_id), {})
    name = p_info.get("full_name", f"Joueur inconnu ({p_id})")
    pos = p_info.get("position", "N/A")
    team = p_info.get("team", "N/A")
    return name, pos, team

df_rosters[["player_name", "position", "team"]] = df_rosters["player_id"].apply(
    lambda x: pd.Series(get_player_info(x))
)

# Calcul du nombre de parts (Exposure) par joueur
exposure = df_rosters.groupby(["player_id", "player_name", "position", "team"]).agg(
    shares=("league_id", "count"),
    leagues=("league_name", lambda x: list(x))
).reset_index()

# Séparation des groupes
group_a = exposure[exposure["shares"] >= threshold_group_a].sort_values(by="shares", ascending=False)
group_b = exposure[exposure["shares"] < threshold_group_a].sort_values(by="shares", ascending=False)

# --- AFFICHAGE INTERFACE STREAMLIT ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

with tab1:
    st.subheader(f"Joueurs clés (≥ {threshold_group_a} parts)")
    st.write(f"Total : **{len(group_a)}** joueurs")
    for _, row in group_a.iterrows():
        with st.expander(f"**{row['player_name']}** ({row['position']} - {row['team']}) — **{row['shares']} parts**"):
            st.caption("Présent dans les ligues suivantes :")
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

with tab2:
    st.subheader(f"Joueurs secondaires (< {threshold_group_a} parts)")
    st.write(f"Total : **{len(group_b)}** joueurs")
    for _, row in group_b.iterrows():
        with st.expander(f"**{row['player_name']}** ({row['position']} - {row['team']}) — **{row['shares']} part(s)**"):
            st.caption("Présent dans les ligues suivantes :")
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

with tab3:
    st.subheader("💡 Opportunités de Trade Détectées")
    st.info("Ce radar cherche dans tes ligues où tu as un **Joueur du Groupe B** si un rival possède un de tes **Joueurs du Groupe A**.")
    
    group_a_ids = set(group_a["player_id"])
    group_b_ids = set(group_b["player_id"])
    
    trades_found = []
    
    # Scanner chaque ligue
    for league in leagues:
        l_id = league["league_id"]
        l_name = league["name"]
        
        # Joueurs du Groupe B que tu possèdes dans CETTE ligue
        my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))]
        
        if my_b_in_league.empty:
            continue
            
        # Charger tous les rosters de la ligue pour trouver qui a tes cibles Groupe A
        rosters_url = f"https://api.sleeper.app/v1/league/{l_id}/rosters"
        rosters = requests.get(rosters_url).json()
        
        for r in rosters:
            if r.get("owner_id") != user_id_input:
                r_players = set(r.get("players") or [])
                # Quels joueurs de ton Groupe A ce manager possède-t-il ?
                target_intersections = r_players.intersection(group_a_ids)
                
                if target_intersections:
                    for target_id in target_intersections:
                        target_name, target_pos, _ = get_player_info(target_id)
                        for _, my_row in my_b_in_league.iterrows():
                            trades_found.append({
                                "Ligue": l_name,
                                "Tu donnes (Groupe B)": f"{my_row['player_name']} ({my_row['position']})",
                                "Tu cibles (Groupe A)": f"{target_name} ({target_pos})",
                                "Propriétaire actuel": r.get("owner_id", "Adversaire")
                            })

    if trades_found:
        df_trades = pd.DataFrame(trades_found)
        st.dataframe(df_trades, use_container_width=True)
    else:
        st.write("Aucune correspondance directe trouvée pour le moment.")
      
