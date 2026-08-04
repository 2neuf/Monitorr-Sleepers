import math
from datetime import datetime
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Sleeper Roster Manager", layout="wide")

def get_asset_value(rank):
    if not rank or rank >= 9000:
        return 100
    val = round(10000 * math.exp(-0.018 * (rank - 1)))
    return max(50, val)

# --- BDD TURSO & SQLITE LOCAL ---

def execute_turso_query(statements):
    turso_url = st.secrets.get("TURSO_DATABASE_URL", "")
    turso_token = st.secrets.get("TURSO_AUTH_TOKEN", "")
    if not turso_url or not turso_token:
        return None
    http_url = turso_url.replace("libsql://", "https://")
    pipeline_url = f"{http_url}/v2/pipeline"
    headers = {"Authorization": f"Bearer {turso_token}", "Content-Type": "application/json"}
    
    requests_payload = []
    for stmt in statements:
        sql = stmt[0]
        args = stmt[1] if len(stmt) > 1 else []
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
        requests_payload.append({"type": "execute", "stmt": {"sql": sql, "args": formatted_args}})
    
    try:
        res = requests.post(pipeline_url, json={"requests": requests_payload}, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def init_db():
    queries = [
        ("""CREATE TABLE IF NOT EXISTS trade_history (
            id TEXT PRIMARY KEY, date TEXT, status TEXT, league TEXT, owner TEXT,
            target_id TEXT, target_name TEXT, target_full TEXT, offered_full TEXT, offered_names TEXT, value_metrics TEXT
        )""", ()),
        ("""CREATE TABLE IF NOT EXISTS blacklist (
            id TEXT PRIMARY KEY, type TEXT, owner TEXT, target_name TEXT, league TEXT
        )""", ())
    ]
    res = execute_turso_query(queries)
    if res is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute("""CREATE TABLE IF NOT EXISTS trade_history (
            id TEXT PRIMARY KEY, date TEXT, status TEXT, league TEXT, owner TEXT,
            target_id TEXT, target_name TEXT, target_full TEXT, offered_full TEXT, offered_names TEXT, value_metrics TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS blacklist (
            id TEXT PRIMARY KEY, type TEXT, owner TEXT, target_name TEXT, league TEXT
        )""")
        conn.commit()
        conn.close()

def load_trades_from_db():
    init_db()
    res = execute_turso_query([("SELECT id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names, value_metrics FROM trade_history", ())])
    trades = []
    if res and "results" in res and res["results"]:
        result_exec = res["results"][0]
        if result_exec.get("type") == "ok":
            for r in result_exec.get("response", {}).get("result", {}).get("rows", []):
                trades.append({
                    "id": r[0]["value"], "date": r[1]["value"], "status": r[2]["value"],
                    "league": r[3]["value"], "owner": r[4]["value"],
                    "target_id": r[5]["value"] if r[5]["type"] != "null" else "",
                    "target_name": r[6]["value"], "target_full": r[7]["value"],
                    "offered_full": r[8]["value"],
                    "offered_names": r[9]["value"].split(";") if r[9]["value"] else [],
                    "value_metrics": r[10]["value"] if len(r) > 10 and r[10]["type"] != "null" else ""
                })
            return trades
    try:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names, value_metrics FROM trade_history")
        for r in cursor.fetchall():
            trades.append({
                "id": r[0], "date": r[1], "status": r[2], "league": r[3], "owner": r[4],
                "target_id": r[5], "target_name": r[6], "target_full": r[7], "offered_full": r[8],
                "offered_names": r[9].split(";") if r[9] else [], "value_metrics": r[10] if len(r) > 10 and r[10] else ""
            })
        conn.close()
    except Exception:
        pass
    return trades

def load_blacklist_from_db():
    init_db()
    res = execute_turso_query([("SELECT id, type, owner, target_name, league FROM blacklist", ())])
    blacklisted_owners = set()
    blacklisted_targets = set()
    
    if res and "results" in res and res["results"]:
        result_exec = res["results"][0]
        if result_exec.get("type") == "ok":
            for r in result_exec.get("response", {}).get("result", {}).get("rows", []):
                b_type = r[1]["value"]
                if b_type == "owner":
                    blacklisted_owners.add(r[2]["value"])
                else:
                    blacklisted_targets.add((r[3]["value"], r[4]["value"], r[2]["value"]))
            return blacklisted_owners, blacklisted_targets

    try:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, type, owner, target_name, league FROM blacklist")
        for r in cursor.fetchall():
            if r[1] == "owner":
                blacklisted_owners.add(r[2])
            else:
                blacklisted_targets.add((r[3], r[4], r[2]))
        conn.close()
    except Exception:
        pass
    return blacklisted_owners, blacklisted_targets

def add_to_blacklist_db(b_id, b_type, owner, target_name="", league=""):
    init_db()
    sql = "INSERT OR REPLACE INTO blacklist (id, type, owner, target_name, league) VALUES (?, ?, ?, ?, ?)"
    args = (b_id, b_type, owner, target_name, league)
    if execute_turso_query([(sql, args)]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute(sql, args)
        conn.commit()
        conn.close()

def remove_from_blacklist_db(b_id):
    init_db()
    sql = "DELETE FROM blacklist WHERE id = ?"
    if execute_turso_query([(sql, (b_id,))]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute(sql, (b_id,))
        conn.commit()
        conn.close()

def save_trade_to_db(trade):
    init_db()
    sql = """INSERT OR REPLACE INTO trade_history 
             (id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names, value_metrics)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    args = (
        trade["id"], trade["date"], trade["status"], trade["league"], trade["owner"],
        str(trade.get("target_id", "")), trade["target_name"], trade["target_full"],
        trade["offered_full"], ";".join(trade["offered_names"]), trade.get("value_metrics", "")
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
    if execute_turso_query([(sql, (status, trade_id))]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute(sql, (status, trade_id))
        conn.commit()
        conn.close()

def delete_all_trades_db():
    init_db()
    if execute_turso_query([("DELETE FROM trade_history", ())]) is None:
        import sqlite3
        conn = sqlite3.connect("trade_history.db")
        conn.execute("DELETE FROM trade_history")
        conn.commit()
        conn.close()

if "trade_history" not in st.session_state:
    st.session_state["trade_history"] = load_trades_from_db()

if "blacklisted_owners" not in st.session_state or "blacklisted_targets" not in st.session_state:
    bo, bt = load_blacklist_from_db()
    st.session_state["blacklisted_owners"] = bo
    st.session_state["blacklisted_targets"] = bt

st.title("🏈 Sleeper Roster Manager")
st.caption("Consolide tes rosters, trie par ADP et suis tes propositions de trade.")

def save_trade_callback(select_key, trade_entry):
    st.session_state["trade_history"].append(trade_entry)
    save_trade_to_db(trade_entry)
    st.session_state[select_key] = []

# --- API SLEEPER ---

@st.cache_data(ttl=86400)
def load_sleeper_players():
    res = requests.get("https://api.sleeper.app/v1/players/nfl")
    return res.json() if res.status_code == 200 else {}

@st.cache_data(ttl=3600)
def fetch_league_users(league_id):
    try:
        res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users").json()
        return {u["user_id"]: u.get("display_name") or u.get("username") or "Anonyme" for u in res}
    except Exception:
        return {}

@st.cache_data(ttl=600)
def fetch_league_rosters(league_id):
    try:
        return requests.get(f"https://api.sleeper.app/v1/league/{league_id}/rosters").json()
    except Exception:
        return []

@st.cache_data(ttl=600)
def fetch_user_leagues(user_id, year):
    try:
        return requests.get(f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}").json()
    except Exception:
        return []

@st.cache_data(ttl=600)
def fetch_league_traded_picks(league_id):
    try:
        return requests.get(f"https://api.sleeper.app/v1/league/{league_id}/traded_picks").json()
    except Exception:
        return []

@st.cache_data(ttl=1800)
def fetch_league_draft_info(league_id):
    try:
        drafts = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/drafts").json()
        if not drafts:
            return {}, set()
        completed_seasons = set()
        roster_to_slot = {}
        for d in drafts:
            d_season = str(d.get("season"))
            if d.get("status") == "complete":
                completed_seasons.add(d_season)
            else:
                draft_id = d.get("draft_id")
                if draft_id:
                    try:
                        d_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}").json()
                        slot_to_roster = d_res.get("slot_to_roster_id") or {}
                        for slot_str, roster_id in slot_to_roster.items():
                            roster_to_slot[int(roster_id)] = int(slot_str)
                    except Exception:
                        pass
        return roster_to_slot, completed_seasons
    except Exception:
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

# --- SIDEBAR & PARAMÈTRES ---
st.sidebar.header("⚙️ Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

rank_threshold_b = st.sidebar.number_input(
    "Rank ADP max. asset Groupe B",
    min_value=10, max_value=300, value=100, step=10,
    help="Exclut par défaut les ligues n'ayant aucun JOUEUR du Groupe B sous ce rang ADP."
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
    help="Ligues exclues automatiquement par manque d'assets solides en Groupe B."
)

# --- GESTION BLACKLIST DANS LA SIDEBAR ---
with st.sidebar.expander("🚫 Gestion Blacklist", expanded=False):
    st.caption("Owners totalement ignorés :")
    if st.session_state["blacklisted_owners"]:
        for bo in list(st.session_state["blacklisted_owners"]):
            col_b1, col_b2 = st.columns([3, 1])
            col_b1.write(f"• **@{bo}**")
            if col_b2.button("❌", key=f"del_bo_{bo}"):
                st.session_state["blacklisted_owners"].remove(bo)
                remove_from_blacklist_db(f"owner_{bo}")
                st.rerun()
    else:
        st.write(":gray[Aucun owner blacklisté.]")

    st.caption("Offres/Cibles spécifiques refusées :")
    if st.session_state["blacklisted_targets"]:
        for bt_item in list(st.session_state["blacklisted_targets"]):
            t_name, l_name, o_name = bt_item
            col_bt1, col_bt2 = st.columns([3, 1])
            col_bt1.write(f"• **{t_name}** ({l_name})")
            if col_bt2.button("❌", key=f"del_bt_{t_name}_{l_name}"):
                st.session_state["blacklisted_targets"].remove(bt_item)
                remove_from_blacklist_db(f"target_{t_name}_{l_name}_{o_name}")
                st.rerun()
    else:
        st.write(":gray[Aucune cible bloquée.]")

pending_trades = [t for t in st.session_state["trade_history"] if t["status"] == "En cours"]
pending_target_pairs = set((t["target_name"], t["league"]) for t in pending_trades)
pending_offered_pairs = set((p_name, t["league"]) for t in pending_trades for p_name in t["offered_names"])

# --- NAVIGATION ONGLETS ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

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
                        status_options = [
                            "En cours", 
                            "Accepté", 
                            "Refusé", 
                            "⛔ Blacklister cet Owner (Partout)", 
                            "🚫 Rejeter ce Deal (Cette ligue)"
                        ]
                        new_st = st.selectbox(
                            "Statut",
                            status_options,
                            index=0,
                            key=f"pinned_status_{p_trade['id']}_{p_idx}"
                        )
                        
                        if new_st != "En cours":
                            if new_st == "⛔ Blacklister cet Owner (Partout)":
                                o_name = p_trade["owner"]
                                st.session_state["blacklisted_owners"].add(o_name)
                                add_to_blacklist_db(f"owner_{o_name}", "owner", o_name)
                                update_trade_status_in_db(p_trade["id"], "Owner Blacklisté")
                                st.toast(f"Owner @{o_name} ajouté à la blacklist.", icon="⛔")
                            elif new_st == "🚫 Rejeter ce Deal (Cette ligue)":
                                t_tuple = (p_trade["target_name"], p_trade["league"], p_trade["owner"])
                                st.session_state["blacklisted_targets"].add(t_tuple)
                                add_to_blacklist_db(f"target_{p_trade['target_name']}_{p_trade['league']}_{p_trade['owner']}", "target", p_trade["owner"], p_trade["target_name"], p_trade["league"])
                                update_trade_status_in_db(p_trade["id"], "Deal Rejeté")
                                st.toast("Offre rejetée et masquée du radar.", icon="🚫")
                            else:
                                update_trade_status_in_db(p_trade["id"], new_st)
                                if new_st == "Accepté":
                                    st.toast("Trade accepté ! Effectifs mis à jour.", icon="✅")

                            for item in st.session_state["trade_history"]:
                                if item["id"] == p_trade["id"]:
                                    item["status"] = new_st
                            st.rerun()

                    with col_dt:
                        metrics_tag = f" `[{p_trade['value_metrics']}]`" if p_trade.get("value_metrics") else ""
                        st.caption(f"Proposé le {p_trade['date']}")
                        st.markdown(f"🤝 **Assets offerts :** {p_trade['offered_full']}{metrics_tag}")

            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("---")

    st.subheader("💡 Opportunités de Trade Détectées")

    if target_opportunities:
        # FILTRAGE AVEC LA BLACKLIST (OWNERS & TARGETS CIBLÉES)
        radar_opps = [
            o for o in target_opportunities 
            if o["league_name"] not in excluded_leagues_input
            and o["owner_pseudo"] not in st.session_state["blacklisted_owners"]
            and (o["target_name"], o["league_name"], o["owner_pseudo"]) not in st.session_state["blacklisted_targets"]
            and (o["target_name"], o["league_name"]) not in pending_target_pairs
        ]

        col_f1, col_f2 = st.columns(2)
        raw_leagues = list(set(o["league_name"] for o in radar_opps))
        sorted_leagues = sorted(raw_leagues, key=lambda name: (-league_size_map.get(name, 0), name))
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
                if len(opps_list) > 1:
                    league_options = [f"🏟️ {o['league_name']} (@{o['owner_pseudo']})" for o in opps_list]
                    selected_league_label = st.selectbox(
                        "Choisir la ligue :",
                        options=league_options,
                        key=f"select_league_for_player_{target_name}_{player_idx}"
                    )
                    selected_idx = league_options.index(selected_league_label)
                else:
                    selected_idx = 0
                    st.caption(f"🏟️ Ligue : **{first_opp['league_name']}** | Owner : **@{first_opp['owner_pseudo']}**")

                opp = opps_list[selected_idx]

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
                                index=["En cours", "Accepté", "Refusé"].index(current_status) if current_status in ["En cours", "Accepté", "Refusé"] else 0,
                                key=f"status_select_{trade['id']}_{player_idx}_{selected_idx}"
                            )
                            if new_status != current_status:
                                st.session_state["trade_history"][real_idx]["status"] = new_status
                                update_trade_status_in_db(trade["id"], new_status)
                                if new_status == "Accepté":
                                    st.toast("Trade accepté ! Effectifs mis à jour.", icon="✅")
                                st.rerun()

                        with col_details:
                            metrics_tag = f" `[{trade['value_metrics']}]`" if trade.get("value_metrics") else ""
                            st.caption(f"Créé le {trade['date']}")
                            if trade["status"] == "Refusé":
                                st.markdown(f"❌ **Proposé(s) :** :red[{trade['offered_full']}]{metrics_tag}")
                            elif trade["status"] == "Accepté":
                                st.markdown(f"✅ **Accepté :** :green[{trade['offered_full']}]{metrics_tag}")
                            else:
                                st.markdown(f"🤝 **Proposé(s) :** {trade['offered_full']}{metrics_tag}")
                    st.divider()

                st.markdown("👉 **Nouvelle proposition pour cette ligue :**")

                key_select = f"select_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{player_idx}_{selected_idx}"
                key_btn = f"btn_{opp['league_name']}_{opp['target_name']}_{opp['owner_pseudo']}_{player_idx}_{selected_idx}"

                selected_offers = st.multiselect(
                    "Assets disponibles (Joueurs Groupe B + Draft Picks, triés par ADP) :",
                    options=opp["b_options"],
                    key=key_select
                )

                # ASSISTANT DE TRADE
                target_val = get_asset_value(opp["target_rank"])

                if selected_offers:
                    offered_ranks = []
                    for opt in selected_offers:
                        if "Rank #" in opt:
                            r_val = int(opt.split("Rank #")[1].split("]")[0].strip())
                            offered_ranks.append(r_val)
                        else:
                            offered_ranks.append(200)

                    offered_val = sum(get_asset_value(r) for r in offered_ranks)
                    diff_pct = round(((offered_val - target_val) / target_val) * 100)
                    sign = "+" if diff_pct >= 0 else ""

                    col_v1, col_v2, col_v3 = st.columns(3)
                    col_v1.metric("🎯 Cible", f"{target_val:,} pts")
                    col_v2.metric("💼 Ton offre", f"{offered_val:,} pts")

                    if diff_pct >= 15:
                        col_v3.metric("⚖️ Bilan", f"+{diff_pct}%", delta="🟢 Offre très forte", delta_color="normal")
                    elif diff_pct >= -10:
                        col_v3.metric("⚖️ Bilan", f"{diff_pct}%", delta="🟢 Équilibré", delta_color="normal")
                    else:
                        col_v3.metric("⚖️ Bilan", f"{diff_pct}%", delta="🔴 Insuffisant", delta_color="inverse")

                    raw_names = [opp["b_names_map"][opt] for opt in selected_offers]
                    trade_entry = {
                        "id": f"{opp['league_name']}_{opp['target_name']}_{datetime.now().timestamp()}",
                        "date": datetime.now().strftime("%d/%m %H:%M"),
                        "status": "En cours",
                        "league": opp["league_name"],
                        "owner": opp["owner_pseudo"],
                        "target_id": opp["target_id"],
                        "target_name": opp["target_name"],
                        "target_full": f"{opp['target_name']} ({opp['target_pos']})",
                        "offered_full": ", ".join(selected_offers),
                        "offered_names": raw_names,
                        "value_metrics": f"{offered_val:,} vs {target_val:,} pts ({sign}{diff_pct}%)"
                    }
                    st.button(
                        "📌 Enregistrer cette proposition",
                        key=key_btn,
                        on_click=save_trade_callback,
                        args=(key_select, trade_entry)
                    )
                else:
                    st.info(f"💡 **Valeur estimée de la cible :** {target_val:,} pts. Sélectionne tes assets pour calculer l'équilibre.")
                    st.button("📌 Enregistrer cette proposition", key=key_btn, disabled=True)

        if st.session_state["trade_history"]:
            st.markdown("---")
            if st.button("🗑️ Effacer l'ensemble de l'historique"):
                st.session_state["trade_history"] = []
                delete_all_trades_db()
                st.rerun()

    else:
        st.info("Aucune opportunité directe trouvée.")
