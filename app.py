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

# Priorité de tri par poste
POS_ORDER = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "K": 5, "DEF": 6}

# 1. Chargement de la base de données globale des joueurs Sleeper (Mise en cache)
@st.cache_data(ttl=86400)
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return {}

# 2. Chargement des membres d'une ligue pour associer Owner ID -> Pseudo
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

# Chargement
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

# Calcul du nombre de parts (Exposure)
exposure = df_rosters.groupby(["player_id", "player_name", "position", "team"]).agg(
    shares=("league_id", "count"),
    leagues=("league_name", lambda x: list(x))
).reset_index()

# Ajouter l'ordre des postes pour le tri
exposure["pos_rank"] = exposure["position"].map(lambda x: POS_ORDER.get(x, 99))

# Séparation des groupes avec tri par poste puis par parts
group_a = exposure[exposure["shares"] >= threshold_group_a].sort_values(by=["pos_rank", "shares"], ascending=[True, False])
group_b = exposure[exposure["shares"] < threshold_group_a].sort_values(by=["pos_rank", "shares"], ascending=[True, False])

# --- INTERFACE STREAMLIT ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

# --- ONGLET 1 : GROUPE A ---
with tab1:
    st.subheader(f"Joueurs clés (≥ {threshold_group_a} parts)")
    
    col_filter, _ = st.columns([1, 2])
    with col_filter:
        pos_filter_a = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_a")
    
    filtered_a = group_a if pos_filter_a == "Tous" else group_a[group_a["position"] == pos_filter_a]
    st.write(f"Total : **{len(filtered_a)}** joueurs")
    
    for _, row in filtered_a.iterrows():
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — **{row['shares']} parts**"):
            st.caption("Présent dans tes ligues :")
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
            st.caption("Présent dans tes ligues :")
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

# --- ONGLET 3 : RADAR DE TRADE ---
with tab3:
    st.subheader("💡 Opportunités de Trade Détectées")
    st.caption("Clique sur une ligne pour voir quel(s) joueur(s) de ton Groupe B tu peux proposer à ce propriétaire.")
    
    group_a_ids = set(group_a["player_id"])
    group_b_ids = set(group_b["player_id"])
    
    target_opportunities = []
    
    # Scanner les ligues
    with st.spinner("Analyse des rosters adverses..."):
        for league in leagues:
            l_id = league["league_id"]
            l_name = league["name"]
            
            # Tes joueurs B dans cette ligue
            my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))]
            if my_b_in_league.empty:
                continue
            
            # Charger les pseudos des utilisateurs de cette ligue
            league_users = fetch_league_users(l_id)
            
            # Charger tous les rosters
            rosters_url = f"https://api.sleeper.app/v1/league/{l_id}/rosters"
            rosters = requests.get(rosters_url).json()
            
            for r in rosters:
                if r.get("owner_id") != user_id_input:
                    r_players = set(r.get("players") or [])
                    # Quels joueurs du Groupe A ce rival possède-t-il ?
                    targets_held = r_players.intersection(group_a_ids)
                    
                    if targets_held:
                        owner_pseudo = league_users.get(r.get("owner_id"), "Propriétaire Inconnu")
                        
                        for target_id in targets_held:
                            t_name, t_pos, t_team = get_player_info(target_id)
                            
                            # Liste de tes joueurs B proposables dans cette ligue
                            b_proposals = []
                            for _, my_row in my_b_in_league.iterrows():
                                b_proposals.append(f"**{my_row['player_name']}** ({my_row['position']} - {my_row['team']})")
                            
                            target_opportunities.append({
                                "target_name": t_name,
                                "target_pos": t_pos,
                                "target_team": t_team,
                                "league_name": l_name,
                                "owner_pseudo": owner_pseudo,
                                "b_proposals": b_proposals
                            })

    if target_opportunities:
        st.write(f"**{len(target_opportunities)}** cible(s) identifiée(s) :")
        for opp in target_opportunities:
            # Ligne unique par cible
            header_text = f"🎯 **{opp['target_name']}** ({opp['target_pos']}) | Ligue: *{opp['league_name']}* | Owner: **@{opp['owner_pseudo']}**"
            
            # Au clic sur la ligne, on affiche les options
            with st.expander(header_text):
                st.markdown("👉 **Joueur(s) du Groupe B que tu possèdes dans cette ligue :**")
                for prop in opp["b_proposals"]:
                    st.markdown(f"• {prop}")
    else:
        st.info("Aucune opportunité directe trouvée entre tes joueurs du Groupe B et les cibles du Groupe A.")
        
