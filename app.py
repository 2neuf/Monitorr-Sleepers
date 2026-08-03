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

# Sidebar pour les paramètres uniquement
st.sidebar.header("⚙️ Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

# Callback pour enregistrer et réinitialiser le multiselect proprement
def save_trade_callback(select_key, trade_entry):
    st.session_state["trade_history"].append(trade_entry)
    st.session_state[select_key] = []

# --- FONCTIONS API & CACHE ---

@st.cache_data(ttl=86400)
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else {}

@st.cache_data(ttl=3600)
def fetch_league_users(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    try:
        res = requests.get(url).json()
        return {u["user_id"]: u.get("display_name") or u.get("username") or "Anonyme" for u in res}
    except:
        return {}

@st.cache_data(ttl=600)
def fetch_league_rosters(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    try:
        return requests.get(url).json()
    except:
        return []

@st.cache_data(ttl=600)
def fetch_user_leagues(user_id, year):
    url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}"
    try:
        return requests.get(url).json()
    except:
        return []

# --- CALCUL GLOBAL EN CACHE ---
@st.cache_data(ttl=600)
def compute_all_data_and_opportunities(user_id, year, threshold_a):
    all_players = load_sleeper_players()
    leagues = fetch_user_leagues(user_id, year)
    
    if not leagues:
        return None, None, None, [], [], {}

    # Carte de la taille des rosters par ligue (nombre de slots configurés)
    league_size_map = {
        league["name"]: len(league.get("roster_positions") or [])
        for league in leagues
    }

    user_rosters = []
    for league in leagues:
        l_id = league["league_id"]
        rosters = fetch_league_rosters(l_id)
        for roster in rosters:
            if roster.get("owner_id") == user_id:
                for p_id in (roster.get("players") or []):
                    user_rosters.append({
                        "player_id": p_id,
                        "league_id": l_id,
                        "league_name": league["name"]
                    })
                    
    if not user_rosters:
        return None, None, None, [], [], {}

    df_rosters = pd.DataFrame(user_rosters)

    def _get_info(p_id):
        p_info = all_players.get(str(p_id), {})
        return (
            p_info.get("full_name", f"Joueur inconnu ({p_id})"),
            p_info.get("position", "N/A"),
            p_info.get("team", "N/A"),
            p_info.get("search_rank") or 9999
        )

    df_rosters[["player_name", "position", "team", "search_rank"]] = df_rosters["player_id"].apply(
        lambda x: pd.Series(_get_info(x))
    )

    exposure = df_rosters.groupby(["player_id", "player_name", "position", "team", "search_rank"]).agg(
        shares=("league_id", "count"),
        leagues=("league_name", lambda x: list(x))
    ).reset_index()

    group_a = exposure[exposure["shares"] >= threshold_a].sort_values(by="search_rank", ascending=True)
    group_b = exposure[exposure["shares"] < threshold_a].sort_values(by="search_rank", ascending=True)

    group_a_ids = set(group_a["player_id"])
    group_b_ids = set(group_b["player_id"])

    target_opportunities = []

    for league in leagues:
        l_id = league["league_id"]
        l_name = league["name"]

        my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))]
        if my_b_in_league.empty:
            continue

        league_users = fetch_league_users(l_id)
        rosters = fetch_league_rosters(l_id)

        for r in rosters:
            if r.get("owner_id") != user_id:
                r_players = set(r.get("players") or [])
                targets_held = r_players.intersection(group_a_ids)

                if targets_held:
                    owner_pseudo = league_users.get(r.get("owner_id"), "Propriétaire Inconnu")

                    for target_id in targets_held:
                        t_name, t_pos, t_team, t_rank = _get_info(target_id)
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
    return df_rosters, group_a, group_b, target_opportunities, leagues, league_size_map


# --- CHARGEMENT ET CALCUL ---
with st.spinner("Analyse et calcul des opportunités..."):
    df_rosters, group_a, group_b, target_opportunities, leagues, league_size_map = compute_all_data_and_opportunities(
        user_id_input, season_year, threshold_group_a
    )

if df_rosters is None:
    st.warning("Aucun roster trouvé pour cet utilisateur/saison.")
    st.stop()

# Extraction des paires (Nom, Ligue) actuellement "En cours"
pending_trades = [t for t in st.session_state["trade_history"] if t["status"] == "En cours"]
pending_target_pairs = set((t["target_name"], t["league"]) for t in pending_trades)
pending_offered_pairs = set((p_name, t["league"]) for t in pending_trades for p_name in t["offered_names"])


# --- NAVIGATION PAR ONGLETS EN HAUT DE PAGE ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

# ONGLET 1 : GROUPE A
with tab1:
    st.subheader(f"Joueurs clés (≥ {threshold_group_a} parts) — Triés par ADP")
    col_filter_a, _ = st.columns([1, 2])
    with col_filter_a:
        pos_filter_a = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_a")

    filtered_a = group_a if pos_filter_a == "Tous" else group_a[group_a["position"] == pos_filter_a]
    st.write(f"Total : **{len(filtered_a)}** joueurs")

    for _, row in filtered_a.iterrows():
        rank_str = f"Rank #{row['search_rank']}" if row['search_rank'] < 9000 else "Non classé"
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — *{rank_str}* — **{row['shares']} parts**"):
            for l_name in row["leagues"]:
                is_pending = (row['player_name'], l_name) in pending_target_pairs or (row['player_name'], l_name) in pending_offered_pairs
                tag = " :gray[⏳ (Trade en cours)]" if is_pending else ""
                st.markdown(f"• {l_name}{tag}")

# ONGLET 2 : GROUPE B
with tab2:
    st.subheader(f"Joueurs secondaires (< {threshold_group_a} parts) — Triés par ADP")
    col_filter_b, _ = st.columns([1, 2])
    with col_filter_b:
        pos_filter_b = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_b")

    filtered_b = group_b if pos_filter_b == "Tous" else group_b[group_b["position"] == pos_filter_b]
    st.write(f"Total : **{len(filtered_b)}** joueurs")

    for _, row in filtered_b.iterrows():
        rank_str = f"Rank #{row['search_rank']}" if row['search_rank'] < 9000 else "Non classé"
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — *{rank_str}* — **{row['shares']} part(s)**"):
            for l_name in row["leagues"]:
                is_pending = (row['player_name'], l_name) in pending_target_pairs or (row['player_name'], l_name) in pending_offered_pairs
                tag = " :gray[⏳ (Trade en cours)]" if is_pending else ""
                st.markdown(f"• {l_name}{tag}")

# ONGLET 3 : RADAR DE TRADE
with tab3:
    st.subheader("💡 Opportunités de Trade Détectées")

    if target_opportunities:
        col_f1, col_f2 = st.columns(2)
        
        # Tri des ligues par taille de roster décroissante (-taille), puis alphabétique
        raw_leagues = list(set(o["league_name"] for o in target_opportunities))
        sorted_leagues = sorted(
            raw_leagues,
            key=lambda name: (-league_size_map.get(name, 0), name)
        )
        all_leagues = ["Toutes"] + sorted_leagues
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
            is_target_pending = (opp["target_name"], opp["league_name"]) in pending_target_pairs
            status_tag = " ⏳ [Trade en cours]" if is_target_pending else ""
            rank_str = f"Rank #{opp['target_rank']}" if opp['target_rank'] < 9000 else "Unranked"

            header_text = f"🎯 **{opp['target_name']}** ({opp['target_pos']}) - *{rank_str}* | Ligue : *{opp['league_name']}* | Owner : **@{opp['owner_pseudo']}**{status_tag}"

            with st.expander(header_text):
                matching_trades = [
                    (real_idx, trade) for real_idx, trade in enumerate(st.session_state["trade_history"])
                    if trade["league"] == opp["league_name"] 
                    and trade["target_name"] == opp["target_name"] 
                    and trade["owner"] == opp["owner_pseudo"]
                ]

                if matching_trades:
                    st.markdown("📋 **Propositions enregistrées pour ce trade :**")
                    for real_idx, trade in matching_trades:
                        col_status, col_details = st.columns([1, 2])
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
                            st.caption(f"Créé le {trade['date']}")
                            if trade["status"] == "Refusé":
                                st.markdown(f"❌ **Proposé(s) :** :red[{trade['offered_full']}]")
                            else:
                                st.markdown(f"🤝 **Proposé(s) :** {trade['offered_full']}")
                    st.divider()

                st.markdown("👉 **Nouvelle proposition pour cette cible :**")

                key_select = f"select_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{idx}"
                key_btn = f"btn_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{idx}"

                selected_offers = st.multiselect(
                    "Joueurs du Groupe B disponibles (triés par ADP) :",
                    options=opp["b_options"],
                    key=key_select
                )

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
                    st.button(
                        "📌 Enregistrer cette proposition",
                        key=key_btn,
                        on_click=save_trade_callback,
                        args=(key_select, trade_entry)
                    )
                else:
                    st.button("📌 Enregistrer cette proposition", key=key_btn, disabled=True)

        if st.session_state["trade_history"]:
            st.markdown("---")
            if st.button("🗑️ Effacer l'ensemble de l'historique"):
                st.session_state["trade_history"] = []
                st.rerun()

    else:
        st.info("Aucune opportunité directe trouvée.")
