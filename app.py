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

@st.cache_data(ttl=600)
def fetch_league_traded_picks(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/traded_picks"
    try:
        return requests.get(url).json()
    except:
        return []

@st.cache_data(ttl=1800)
def fetch_league_draft_info(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/drafts"
    try:
        drafts = requests.get(url).json()
        if not drafts:
            return {}, set()
        
        completed_seasons = set()
        roster_to_slot = {}

        for d in drafts:
            d_season = str(d.get("season"))
            d_status = d.get("status")
            
            if d_status == "complete":
                completed_seasons.add(d_season)
            else:
                draft_id = d.get("draft_id")
                if draft_id:
                    try:
                        d_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}").json()
                        slot_to_roster = d_res.get("slot_to_roster_id") or {}
                        for slot_str, roster_id in slot_to_roster.items():
                            roster_to_slot[int(roster_id)] = int(slot_str)
                    except:
                        pass

        return roster_to_slot, completed_seasons
    except:
        return {}, set()

# --- CALCUL LOGARITHMIQUE DE LA VALEUR D'UN PICK ---
def calculate_pick_rank_and_label(season, rd, orig_id, my_roster_id, roster_to_slot, total_teams, orig_pseudo, current_year):
    slot = roster_to_slot.get(orig_id) if season == str(current_year) else None
    
    if slot is not None:
        pos_in_round = slot
        slot_str = f"{rd}.{slot:02d}" if slot < 10 else f"{rd}.{slot}"
    else:
        pos_in_round = (total_teams + 1) / 2.0
        slot_str = None
        
    abs_pos = (rd - 1) * total_teams + pos_in_round
    year_diff = max(0, int(season) - int(current_year))
    year_penalty = year_diff * 25
    
    rank_val = round(15 + ((abs_pos ** 1.15) * 0.9) + year_penalty)
    
    rd_tag = "1er" if rd == 1 else f"{rd}eme"
    orig_tag = f" ({orig_pseudo})" if orig_id != my_roster_id else ""
    
    if slot_str:
        label = f"🎟️ Pick {season} {rd_tag} Rd - {slot_str}{orig_tag} [Est. Rank #{rank_val}]"
        pick_name = f"Pick {season} {slot_str}{orig_tag}"
    else:
        label = f"🎟️ Pick {season} {rd_tag} Rd{orig_tag} [Est. Rank #{rank_val}]"
        pick_name = f"Pick {season} R{rd}{orig_tag}"
        
    return rank_val, label, pick_name

# --- CALCUL GLOBAL EN CACHE ---
@st.cache_data(ttl=600)
def compute_all_data_and_opportunities(user_id, year, threshold_a, excluded_leagues=()):
    all_players = load_sleeper_players()
    leagues = fetch_user_leagues(user_id, year)
    
    if not leagues:
        return None, None, None, [], [], {}

    league_size_map = {
        league["name"]: len(league.get("roster_positions") or [])
        for league in leagues
    }

    user_rosters = []
    user_roster_ids = {}

    for league in leagues:
        l_id = league["league_id"]
        rosters = fetch_league_rosters(l_id)
        for roster in rosters:
            if roster.get("owner_id") == user_id:
                user_roster_ids[l_id] = roster.get("roster_id")
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

        # Filtre d'exclusion du Radar de Trade
        if l_name in excluded_leagues:
            continue

        my_roster_id = user_roster_ids.get(l_id)

        # 1. Joueurs du Groupe B
        my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))].copy()

        # 2. Map des pseudos et slots
        league_users = fetch_league_users(l_id)
        rosters = fetch_league_rosters(l_id)
        total_teams = len(rosters) or league.get("total_rosters", 12)
        
        roster_id_to_pseudo = {}
        for r in rosters:
            r_id = r.get("roster_id")
            o_id = r.get("owner_id")
            roster_id_to_pseudo[r_id] = league_users.get(o_id, f"Équipe #{r_id}")

        roster_to_slot, completed_seasons = fetch_league_draft_info(l_id)

        # 3. Reconstitution des Draft Picks (en excluant les drafts terminées)
        draft_rounds = league.get("settings", {}).get("draft_rounds", 4)
        future_years = [str(int(year) + i) for i in range(0, 3)]
        valid_years = [yr for yr in future_years if yr not in completed_seasons]
        
        owned_picks = set()
        if my_roster_id:
            for yr in valid_years:
                for rd in range(1, draft_rounds + 1):
                    owned_picks.add((yr, rd, my_roster_id))

            traded_picks = fetch_league_traded_picks(l_id)
            for tp in traded_picks:
                tp_season = str(tp.get("season"))
                if tp_season in completed_seasons:
                    continue
                
                tp_round = tp.get("round")
                tp_orig = tp.get("roster_id")
                tp_owner = tp.get("owner_id")

                if tp_orig == my_roster_id and tp_owner != my_roster_id:
                    owned_picks.discard((tp_season, tp_round, tp_orig))
                elif tp_owner == my_roster_id:
                    owned_picks.add((tp_season, tp_round, tp_orig))

        # 4. Construction et valorisation de la liste des assets
        b_sorted = my_b_in_league.sort_values(by="search_rank", ascending=True)
        b_options_list = []

        for _, row in b_sorted.iterrows():
            label = f"🏃 {row['player_name']} ({row['position']} - {row['team']}) [Rank #{row['search_rank']}]"
            b_options_list.append((row['search_rank'], label, row['player_name']))

        for season, rd, orig_id in owned_picks:
            orig_pseudo = roster_id_to_pseudo.get(orig_id, f"#{orig_id}")
            rank_val, label, pick_name = calculate_pick_rank_and_label(
                season, rd, orig_id, my_roster_id, roster_to_slot, total_teams, orig_pseudo, year
            )
            b_options_list.append((rank_val, label, pick_name))

        # Tri complet par valeur d'ADP
        b_options_list.sort(key=lambda x: x[0])
        final_b_options = [opt[1] for opt in b_options_list]
        final_b_names_map = {opt[1]: opt[2] for opt in b_options_list}

        for r in rosters:
            if r.get("owner_id") != user_id:
                r_players = set(r.get("players") or [])
                targets_held = r_players.intersection(group_a_ids)

                if targets_held:
                    owner_pseudo = league_users.get(r.get("owner_id"), "Propriétaire Inconnu")

                    for target_id in targets_held:
                        t_name, t_pos, t_team, t_rank = _get_info(target_id)

                        target_opportunities.append({
                            "target_name": t_name,
                            "target_pos": t_pos,
                            "target_team": t_team,
                            "target_rank": t_rank,
                            "league_name": l_name,
                            "owner_pseudo": owner_pseudo,
                            "b_options": final_b_options,
                            "b_names_map": final_b_names_map
                        })

    target_opportunities.sort(key=lambda x: x["target_rank"])
    return df_rosters, group_a, group_b, target_opportunities, leagues, league_size_map


# --- SIDEBAR & PARAMÈTRES ---
st.sidebar.header("⚙️ Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

# Liste dynamique des ligues pour le champ d'exclusion
user_leagues_raw = fetch_user_leagues(user_id_input, season_year)
all_league_names = sorted([l["name"] for l in user_leagues_raw]) if user_leagues_raw else []

excluded_leagues_input = st.sidebar.multiselect(
    "Exclure des ligues (Radar)",
    options=all_league_names,
    default=[],
    help="Les ligues sélectionnées n'apparaîtront pas dans l'onglet Radar de Trade."
)


# --- CHARGEMENT ET CALCUL ---
with st.spinner("Analyse et calcul des opportunités..."):
    df_rosters, group_a, group_b, target_opportunities, leagues, league_size_map = compute_all_data_and_opportunities(
        user_id_input, season_year, threshold_group_a, tuple(excluded_leagues_input)
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
                    "Assets disponibles (Joueurs du Groupe B + Draft Picks, triés par ADP) :",
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
