import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# Configuration Streamlit pour mobile
st.set_page_config(page_title="Sleeper Roster Manager", layout="wide")

# --- GESTION DE LA BASE DE DONNÉES TURSO (API HTTP) & SECOURS LOCAL ---

def execute_turso_query(statements):
    turso_url = st.secrets.get("TURSO_DATABASE_URL", "")
    turso_token = st.secrets.get("TURSO_AUTH_TOKEN", "")

    if not turso_url or not turso_token:
        return None

    # Conversion d'une URL libsql:// en https://
    http_url = turso_url.replace("libsql://", "https://")
    pipeline_url = f"{http_url}/v2/pipeline"

    headers = {
        "Authorization": f"Bearer {turso_token}",
        "Content-Type": "application/json"
    }

    requests_payload = []
    for stmt in statements:
        sql = stmt[0]
        args = stmt[1] if len(stmt) > 1 else []
        
        # Formatage des arguments pour l'API HTTP de Turso
        formatted_args = []
        for arg in args:
            if arg is None:
                formatted_args.append({"type": "null"})
            elif isinstance(arg, int):
                formatted_args.append({"type": "integer", "value": str(arg)})
            elif isinstance(arg, float):
                formatted_args.append({"type": "float", "value": arg})
            else:
                formatted_args.append({"type": "text", "value": str(arg)})

        requests_payload.append({
            "type": "execute",
            "stmt": {
                "sql": sql,
                "args": formatted_args
            }
        })

    payload = {"requests": requests_payload}

    try:
        res = requests.post(pipeline_url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def init_db():
    res = execute_turso_query([(
        """CREATE TABLE IF NOT EXISTS trade_history (
            id TEXT PRIMARY KEY,
            date TEXT,
            status TEXT,
            league TEXT,
            owner TEXT,
            target_id TEXT,
            target_name TEXT,
            target_full TEXT,
            offered_full TEXT,
            offered_names TEXT
        )""", ()
    )])
    
    # Secours SQLite local si Turso n'est pas configuré
    if res is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id TEXT PRIMARY KEY, date TEXT, status TEXT, league TEXT, owner TEXT,
                target_id TEXT, target_name TEXT, target_full TEXT, offered_full TEXT, offered_names TEXT
            )
        """)
        conn.commit()
        conn.close()

def load_trades_from_db():
    init_db()
    res = execute_turso_query([("SELECT id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names FROM trade_history", ())])
    
    trades = []
    if res and "results" in res and res["results"]:
        result_exec = res["results"][0]
        if result_exec.get("type") == "ok":
            response = result_exec.get("response", {}).get("result", {})
            rows = response.get("rows", [])
            for r in rows:
                trades.append({
                    "id": r[0]["value"],
                    "date": r[1]["value"],
                    "status": r[2]["value"],
                    "league": r[3]["value"],
                    "owner": r[4]["value"],
                    "target_id": r[5]["value"] if r[5]["type"] != "null" else "",
                    "target_name": r[6]["value"],
                    "target_full": r[7]["value"],
                    "offered_full": r[8]["value"],
                    "offered_names": r[9]["value"].split(";") if r[9]["value"] else []
                })
            return trades

    # Fallback SQLite local
    try:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names FROM trade_history")
        for r in cursor.fetchall():
            trades.append({
                "id": r[0], "date": r[1], "status": r[2], "league": r[3], "owner": r[4],
                "target_id": r[5], "target_name": r[6], "target_full": r[7], "offered_full": r[8],
                "offered_names": r[9].split(";") if r[9] else []
            })
        conn.close()
    except Exception:
        pass
    return trades

def save_trade_to_db(trade):
    init_db()
    sql = """INSERT OR REPLACE INTO trade_history 
             (id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    args = (
        trade["id"], trade["date"], trade["status"], trade["league"], trade["owner"],
        str(trade.get("target_id", "")), trade["target_name"], trade["target_full"],
        trade["offered_full"], ";".join(trade["offered_names"])
    )
    
    if execute_turso_query([(sql, args)]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute(sql, args)
        conn.commit()
        conn.close()

def update_trade_status_in_db(trade_id, status):
    init_db()
    sql = "UPDATE trade_history SET status = ? WHERE id = ?"
    args = (status, trade_id)
    if execute_turso_query([(sql, args)]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute(sql, args)
        conn.commit()
        conn.close()

def delete_all_trades_db():
    init_db()
    sql = "DELETE FROM trade_history"
    if execute_turso_query([(sql, ())]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute(sql)
        conn.commit()
        conn.close()

# Initialisation de l'historique en session
if "trade_history" not in st.session_state:
    st.session_state["trade_history"] = load_trades_from_db()

st.title("🏈 Sleeper Roster Manager")
st.caption("Consolide tes rosters, trie par ADP et suis tes propositions de trade.")

def save_trade_callback(select_key, trade_entry):
    st.session_state["trade_history"].append(trade_entry)
    save_trade_to_db(trade_entry)
    st.session_state[select_key] = []

# --- FONCTIONS API SLEEPER & CACHE ---

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


@st.cache_data(ttl=600)
def compute_all_data_and_opportunities(user_id, year, threshold_a, accepted_trades_tuple=()):
    all_players = load_sleeper_players()
    leagues = fetch_user_leagues(user_id, year)
    
    if not leagues:
        return None, None, None, [], [], {}

    league_name_to_id = {l["name"]: l["league_id"] for l in leagues}
    league_size_map = {
        league["name"]: len(league.get("roster_positions") or [])
        for league in leagues
    }

    name_to_player_id = {}
    for p_id, p_info in all_players.items():
        fname = p_info.get("full_name")
        if fname:
            name_to_player_id[fname] = p_id

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
                        "player_id": str(p_id),
                        "league_id": l_id,
                        "league_name": league["name"]
                    })

    traded_away_picks = set()

    for trade_league, target_id, target_name, offered_names in accepted_trades_tuple:
        t_league_id = league_name_to_id.get(trade_league)
        if not t_league_id:
            continue

        acq_id = str(target_id) if target_id else name_to_player_id.get(target_name)
        if acq_id:
            user_rosters.append({
                "player_id": str(acq_id),
                "league_id": t_league_id,
                "league_name": trade_league
            })

        for off_item in offered_names:
            if off_item in name_to_player_id:
                off_p_id = str(name_to_player_id[off_item])
                user_rosters = [
                    r for r in user_rosters
                    if not (r["league_name"] == trade_league and r["player_id"] == off_p_id)
                ]
            else:
                traded_away_picks.add((trade_league, off_item))

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
        my_roster_id = user_roster_ids.get(l_id)

        my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))].copy()

        league_users = fetch_league_users(l_id)
        rosters = fetch_league_rosters(l_id)
        total_teams = len(rosters) or league.get("total_rosters", 12)
        
        roster_id_to_pseudo = {}
        for r in rosters:
            r_id = r.get("roster_id")
            o_id = r.get("owner_id")
            roster_id_to_pseudo[r_id] = league_users.get(o_id, f"Équipe #{r_id}")

        roster_to_slot, completed_seasons = fetch_league_draft_info(l_id)

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
            if (l_name, pick_name) not in traded_away_picks:
                b_options_list.append((rank_val, label, pick_name))

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
                            "target_id": target_id,
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

rank_threshold_b = st.sidebar.number_input(
    "Rank ADP max. asset Groupe B",
    min_value=10,
    max_value=300,
    value=100,
    step=10,
    help="Exclut par défaut les ligues n'ayant aucun JOUEUR du Groupe B (picks exclus) sous ce rang ADP."
)

accepted_trades = [t for t in st.session_state["trade_history"] if t["status"] == "Accepté"]
accepted_trades_tuple = tuple(
    (t["league"], t.get("target_id"), t["target_name"], tuple(t["offered_names"]))
    for t in accepted_trades
)

# --- CHARGEMENT ET CALCUL ---
with st.spinner("Analyse et calcul des opportunités..."):
    df_rosters, group_a, group_b, target_opportunities, leagues, league_size_map = compute_all_data_and_opportunities(
        user_id_input, season_year, threshold_group_a, accepted_trades_tuple
    )

if df_rosters is None:
    st.warning("Aucun roster trouvé pour cet utilisateur/saison.")
    st.stop()

valid_b_players = group_b[group_b["search_rank"] <= rank_threshold_b]

leagues_with_valid_b = set()
for _, row in valid_b_players.iterrows():
    leagues_with_valid_b.update(row["leagues"])

all_league_names = sorted([l["name"] for l in leagues]) if leagues else []
default_excluded_leagues = [lname for lname in all_league_names if lname not in leagues_with_valid_b]

excluded_leagues_input = st.sidebar.multiselect(
    "Exclure des ligues (Radar)",
    options=all_league_names,
    default=default_excluded_leagues,
    help="Ligues exclues automatiquement par manque d'assets solides en Groupe B (modifiable)."
)

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
    # 📌 BLOC ÉPINGLÉ : TRADES EN COURS
    if pending_trades:
        st.markdown(
            """
            <style>
            div[data-testid="stVerticalBlock"] > div.pinned-box {
                background-color: #fff5f5;
                border: 1px solid #feb2b2;
                border-radius: 10px;
                padding: 16px;
                margin-bottom: 25px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        pinned_container = st.container()
        with pinned_container:
            st.markdown('<div class="pinned-box">', unsafe_allow_html=True)
            st.markdown('<h4 style="color: #c53030; margin-top: 0; margin-bottom: 15px;">📌 Trades en Cours Épinglés</h4>', unsafe_allow_html=True)

            for p_idx, p_trade in enumerate(pending_trades):
                with st.expander(f"⏳ **{p_trade['target_full']}** | Ligue : *{p_trade['league']}* | Owner : **@{p_trade['owner']}**", expanded=True):
                    col_st, col_dt = st.columns([1, 2])
                    with col_st:
                        new_st = st.selectbox(
                            "Statut",
                            ["En cours", "Accepté", "Refusé"],
                            index=0,
                            key=f"pinned_status_{p_trade['id']}_{p_idx}"
                        )
                        if new_st != "En cours":
                            update_trade_status_in_db(p_trade["id"], new_st)
                            for item in st.session_state["trade_history"]:
                                if item["id"] == p_trade["id"]:
                                    item["status"] = new_st
                            if new_st == "Accepté":
                                st.toast("Trade accepté ! Effectifs mis à jour.", icon="✅")
                            st.rerun()

                    with col_dt:
                        st.caption(f"Proposé le {p_trade['date']}")
                        st.markdown(f"🤝 **Assets offerts :** {p_trade['offered_full']}")

            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("---")

    st.subheader("💡 Opportunités de Trade Détectées")

    if target_opportunities:
        radar_opps = [
            o for o in target_opportunities 
            if o["league_name"] not in excluded_leagues_input
            and (o["target_name"], o["league_name"]) not in pending_target_pairs
        ]

        col_f1, col_f2 = st.columns(2)
        
        raw_leagues = list(set(o["league_name"] for o in radar_opps))
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

        filtered_opps = radar_opps
        if selected_league != "Toutes":
            filtered_opps = [o for o in filtered_opps if o["league_name"] == selected_league]
        if selected_pos != "Tous":
            filtered_opps = [o for o in filtered_opps if o["target_pos"] == selected_pos]

        # REGROUPEMENT PAR JOUEUR
        grouped_by_player = {}
        for opp in filtered_opps:
            t_name = opp["target_name"]
            if t_name not in grouped_by_player:
                grouped_by_player[t_name] = []
            grouped_by_player[t_name].append(opp)

        st.write(f"**{len(grouped_by_player)}** joueur(s) disponible(s) ({len(filtered_opps)} opportunités au total) :")

        for player_idx, (target_name, opps_list) in enumerate(grouped_by_player.items()):
            first_opp = opps_list[0]
            rank_str = f"Rank #{first_opp['target_rank']}" if first_opp['target_rank'] < 9000 else "Unranked"
            nb_leagues = len(opps_list)
            league_text = f"{nb_leagues} ligue" if nb_leagues == 1 else f"{nb_leagues} ligues"

            player_header = f"🎯 **{target_name}** ({first_opp['target_pos']}) - *{rank_str}* | **{league_text}**"

            with st.expander(player_header):
                # Si le joueur est présent dans plusieurs ligues, on propose un menu déroulant
                league_options = [f"🏟️ {o['league_name']} (@{o['owner_pseudo']})" for o in opps_list]
                
                if len(league_options) > 1:
                    selected_league_label = st.selectbox(
                        "Choisir la ligue à afficher :",
                        options=league_options,
                        key=f"select_league_for_player_{target_name}_{player_idx}"
                    )
                    selected_idx = league_options.index(selected_league_label)
                else:
                    selected_idx = 0

                opp = opps_list[selected_idx]

                st.markdown(f"**Ligue :** `{opp['league_name']}` | **Owner :** `@{opp['owner_pseudo']}`")

                matching_trades = [
                    (real_idx, trade) for real_idx, trade in enumerate(st.session_state["trade_history"])
                    if trade["league"] == opp["league_name"] 
                    and trade["target_name"] == opp["target_name"] 
                    and trade["owner"] == opp["owner_pseudo"]
                ]

                if matching_trades:
                    st.markdown("📋 **Propositions enregistrées :**")
                    for real_idx, trade in matching_trades:
                        col_status, col_details = st.columns([1, 2])
                        with col_status:
                            current_status = trade["status"]
                            new_status = st.selectbox(
                                "Statut",
                                ["En cours", "Accepté", "Refusé"],
                                index=["En cours", "Accepté", "Refusé"].index(current_status),
                                key=f"status_select_{trade['id']}_{player_idx}_{selected_idx}"
                            )
                            if new_status != current_status:
                                st.session_state["trade_history"][real_idx]["status"] = new_status
                                update_trade_status_in_db(trade["id"], new_status)
                                if new_status == "Accepté":
                                    st.toast("Trade accepté ! Effectifs et assets mis à jour.", icon="✅")
                                st.rerun()

                        with col_details:
                            st.caption(f"Créé le {trade['date']}")
                            if trade["status"] == "Refusé":
                                st.markdown(f"❌ **Proposé(s) :** :red[{trade['offered_full']}]")
                            elif trade["status"] == "Accepté":
                                st.markdown(f"✅ **Accepté :** :green[{trade['offered_full']}]")
                            else:
                                st.markdown(f"🤝 **Proposé(s) :** {trade['offered_full']}")
                    st.divider()

                st.markdown("👉 **Nouvelle proposition pour cette ligue :**")

                key_select = f"select_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{player_idx}_{selected_idx}"
                key_btn = f"btn_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{player_idx}_{selected_idx}"

                selected_offers = st.multiselect(
                    "Assets disponibles (Joueurs Groupe B + Draft Picks, triés par ADP) :",
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
                        "target_id": opp["target_id"],
                        "target_name": opp["target_name"],
                        "target_full": f"{opp['target_name']