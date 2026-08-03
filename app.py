import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# Configuration Streamlit pour mobile
st.set_page_config(page_title="Sleeper Roster Manager", layout="wide")

# Initialisation de l'historique des trades
if "trade_history" not in st.session_state:
    st.session_state["trade_history"] = []

st.title("🏈 Sleeper Roster Manager")
st.caption("Consolide tes rosters, trie par ADP et suis tes propositions de trade.")

# Sidebar pour les paramètres
st.sidebar.header("Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

# 1. Base de données globale des joueurs Sleeper
@st.cache_data(ttl=86400)
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return {}

# 2. Chargement des membres d'une ligue (Mise en cache 1h)
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

# 3. NOUVEAU : Chargement des rosters d'une ligue (Mise en cache 10 min)
@st.cache_data(ttl=600)
def fetch_league_rosters(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    try:
        return requests.get(url).json()
    except:
        return []

# 4. Chargement des ligues et rosters de l'utilisateur
@st.cache_data(ttl=600)
def fetch_user_data(user_id, year):
    leagues_url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}"
    leagues = requests.get(leagues_url).json()
    
    user_rosters = []
    league_details = {}

    for league in leagues:
        league_id = league["league_id"]
        league_details[league_id] = league["name"]
        
        rosters = fetch_league_rosters(league_id)
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

# Chargement principal
with st.spinner("Chargement des données Sleeper..."):
    all_players = load_sleeper_players()
    roster_data, league_map, leagues = fetch_user_data(user_id_input, season_year)

if not roster_data:
    st.warning("Aucun roster trouvé pour cet utilisateur/saison.")
    st.stop()

# Extraction des noms engagés dans des trades "En cours"
pending_trades = [t for t in st.session_state["trade_history"] if t["status"] == "En cours"]
pending_targets = set(t["target_name"] for t in pending_trades)
pending_offered = set(p_name for t in pending_trades for p_name in t["offered_names"])

# Transformation des données
df_rosters = pd.DataFrame(roster_data)

def get_player_info(p_id):
    p_info = all_players.get(str(p_id), {})
    name = p_info.get("full_name", f"Joueur inconnu ({p_id})")
    pos = p_info.get("position", "N/A")
    team = p_info.get("team", "N/A")
    rank = p_info.get("search_rank") or 9999
    return name, pos, team, rank

df_rosters[["player_name", "position", "team", "search_rank"]] = df_rosters["player_id"].apply(
    lambda x: pd.Series(get_player_info(x))
)

# Exposition et tri par ADP
exposure = df_rosters.groupby(["player_id", "player_name", "position", "team", "search_rank"]).agg(
    shares=("league_id", "count"),
    leagues=("league_name", lambda x: list(x))
).reset_index()

group_a = exposure[exposure["shares"] >= threshold_group_a].sort_values(by="search_rank", ascending=True)
group_b = exposure[exposure["shares"] < threshold_group_a].sort_values(by="search_rank", ascending=True)

def format_player_label(name, pos, team, rank):
    is_pending = (name in pending_targets) or (name in pending_offered)
    rank_str = f"Rank #{rank}" if rank < 9000 else "Non classé"
    if is_pending:
        return f":gray[[{pos}] {name} ({team}) — {rank_str} ⏳ Trade en cours]"
    return f"**[{pos}] {name}** ({team}) — *{rank_str}*"

# --- INTERFACE ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

# ONGLET 1
with tab1:
    st.subheader(f"Joueurs clés (≥ {threshold_group_a} parts) — Triés par ADP")
    col_filter_a, _ = st.columns([1, 2])
    with col_filter_a:
        pos_filter_a = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_a")
    
    filtered_a = group_a if pos_filter_a == "Tous" else group_a[group_a["position"] == pos_filter_a]
    st.write(f"Total : **{len(filtered_a)}** joueurs")
    
    for _, row in filtered_a.iterrows():
        label = format_player_label(row['player_name'], row['position'], row['team'], row['search_rank'])
        with st.expander(f"{label} — **{row['shares']} parts**"):
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

# ONGLET 2
with tab2:
    st.subheader(f"Joueurs secondaires (< {threshold_group_a} parts) — Triés par ADP")
    col_filter_b, _ = st.columns([1, 2])
    with col_filter_b:
        pos_filter_b = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_b")
        
    filtered_b = group_b if pos_filter_b == "Tous" else group_b[group_b["position"] == pos_filter_b]
    st.write(f"Total : **{len(filtered_b)}** joueurs")
    
    for _, row in filtered_b.iterrows():
        label = format_player_label(row['player_name'], row['position'], row['team'], row['search_rank'])
        with st.expander(f"{label} — **{row['shares']} part(s)**"):
            for l_name in row["leagues"]:
                st.write(f"• {l_name}")

# ONGLET 3
with tab3:
    st.subheader("💡 Opportunités de Trade Détectées")
    
    group_a_ids = set(group_a["player_id"])
    group_b_ids = set(group_b["player_id"])
    
    target_opportunities = []
    
    with st.spinner("Analyse rapide des rosters adverses..."):
        for league in leagues:
            l_id = league["league_id"]
            l_name = league["name"]
            
            my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))]
            if my_b_in_league.empty:
                continue
            
            league_users = fetch_league_users(l_id)
            rosters = fetch_league_rosters(l_id)  # Apport de la mise en cache ici
            
            for r in rosters:
                if r.get("owner_id") != user_id_input:
                    r_players = set(r.get("players") or [])
                    targets_held = r_players.intersection(group_a_ids)
                    
                    if targets_held:
                        owner_pseudo = league_users.get(r.get("owner_id"), "Propriétaire Inconnu")
                        
                        for target_id in targets_held:
                            t_name, t_pos, t_team, t_rank = get_player_info(target_id)
                            
                            b_sorted = my_b_in_league.sort_values(by="search_rank", ascending=True)
                            b_options = [
                                f"{row['player_name']} ({row['position']} - {row['team']}) [Rank #{row['search_rank']}]"
                                for _, row in b_sorted.iterrows()
                            ]
                            b_names_map = {
                                f"{row['player_name']} ({row['position']} - {row['team']}) [Rank #{row['search_rank']}]": row['player_name']
                                for _, row in b_sorted.iterrows()
                            }
                            
                            target_opportunities.append({
                                "target_name": t_name,
                                "target_pos": t_pos,
                                "target_team": t_team,
                                "target_rank": t_rank,
                                "league_name": l_name,
                                "owner_pseudo": owner_pseudo,
                                "b_options": b_options,
                                "b_names_map": b_names_map
                            })

    target_opportunities.sort(key=lambda x: x["target_rank"])

    if target_opportunities:
        col_f1, col_f2 = st.columns(2)
        all_leagues = ["Toutes"] + sorted(list(set(o["league_name"] for o in target_opportunities)))
        all_positions = ["Tous", "QB", "RB", "WR", "TE"]
        
        with col_f1:
            selected_league = st.selectbox("Filtrer par ligue", all_leagues, key="trade_league_filter")
        with col_f2:
            selected_pos = st.selectbox("Filtrer par poste ciblé", all_positions, key="trade_pos_filter")
            
        filtered_opps = target_opportunities
        if selected_league != "Toutes":
            filtered_opps = [o for o in filtered_opps if o["league_name"] == selected_league]
        if selected_pos != "Tous":
            filtered_opps = [o for o in filtered_opps if o["target_pos"] == selected_pos]
            
        st.write(f"**{len(filtered_opps)}** opportunité(s) affichée(s) :")
        
        for idx, opp in enumerate(filtered_opps):
            is_target_pending = opp["target_name"] in pending_targets
            status_tag = " ⏳ [Trade en cours]" if is_target_pending else ""
            rank_str = f"Rank #{opp['target_rank']}" if opp['target_rank'] < 9000 else "Unranked"
            
            header_text = f"🎯 **{opp['target_name']}** ({opp['target_pos']}) - *{rank_str}* | Ligue : *{opp['league_name']}* | Owner : **@{opp['owner_pseudo']}**{status_tag}"
            
            with st.expander(header_text):
                st.markdown("👉 **Sélectionne le ou les joueurs à inclure dans ton offre :**")
                
                key_select = f"select_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{idx}"
                key_btn = f"btn_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{idx}"
                
                selected_offers = st.multiselect(
                    "Joueurs du Groupe B disponibles (triés par ADP) :",
                    options=opp["b_options"],
                    key=key_select
                )
                
                if st.button("📌 Enregistrer cette proposition", key=key_btn):
                    if selected_offers:
                        raw_names = [opp["b_names_map"][opt] for opt in selected_offers]
                        trade_entry = {
                            "id": f"{opp['league_name']}_{opp['target_name']}_{datetime.now().timestamp()}",
                            "date": datetime.now().strftime("%d/%m %H:%M"),
                            "status": "En cours",
                            "league": opp["league_name"],
                            "owner": opp["owner_pseudo"],
                            "target_name": opp["target_name"],
                            "target_full": f"{opp['target_name']} ({opp['target_pos']})",
                            "offered_full": ", ".join(selected_offers),
                            "offered_names": raw_names
                        }
                        st.session_state["trade_history"].append(trade_entry)
                        st.session_state[key_select] = []
                        st.success(f"Offre enregistrée pour {opp['target_name']} !")
                        st.rerun()
                    else:
                        st.warning("Veuillez sélectionner au moins un joueur.")

    else:
        st.info("Aucune opportunité directe trouvée.")

    # HISTORIQUE
    st.markdown("---")
    st.subheader("📋 Historique des Propositions")
    
    if st.session_state["trade_history"]:
        for idx_trade, trade in enumerate(reversed(st.session_state["trade_history"])):
            real_idx = len(st.session_state["trade_history"]) - 1 - idx_trade
            
            col_status, col_details = st.columns([1, 3])
            
            with col_status:
                current_status = trade["status"]
                new_status = st.selectbox(
                    "Statut",
                    ["En cours", "Accepté", "Refusé"],
                    index=["En cours", "Accepté", "Refusé"].index(current_status),
                    key=f"status_select_{trade['id']}"
                )
                
                if new_status == "Accepté":
                    st.session_state["trade_history"].pop(real_idx)
                    st.toast("Trade accepté ! Supprimé de l'historique.", icon="✅")
                    st.rerun()
                elif new_status != current_status:
                    st.session_state["trade_history"][real_idx]["status"] = new_status
                    st.rerun()

            with col_details:
                st.markdown(f"**Ligue :** {trade['league']} | **Adversaire :** @{trade['owner']} | **Date :** {trade['date']}")
                st.markdown(f"🎯 **Cible :** {trade['target_full']}")
                
                if trade["status"] == "Refusé":
                    st.markdown(f"❌ **Proposé(s) :** :red[{trade['offered_full']}]")
                else:
                    st.markdown(f"🤝 **Proposé(s) :** {trade['offered_full']}")
            
            st.divider()

        if st.button("🗑️ Tout effacer l'historique"):
            st.session_state["trade_history"] = []
            st.rerun()
    else:
        st.caption("Aucune proposition enregistrée pour le moment.")
