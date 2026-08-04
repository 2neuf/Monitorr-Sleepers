import streamlit as st
import requests
import sqlite3
import pandas as pd
import numpy as np
import math
from datetime import datetime

# --- CONFIGURATION STREAMLIT ---
st.set_page_config(
    page_title="Empire Trade Radar",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- BASE DE DONNÉES TURSO / SQLITE ---
TURSO_DATABASE_URL = st.secrets.get("TURSO_DATABASE_URL", "sqlite.db")
TURSO_AUTH_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")

def get_db_connection():
    """Établit la connexion avec Turso/SQLite local."""
    conn = sqlite3.connect("local_trade_radar.db")
    return conn

def init_db():
    """Initialise les tables de persistance."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id TEXT PRIMARY KEY,
            date TEXT,
            status TEXT,
            league TEXT,
            owner TEXT,
            target_id TEXT,
            target_name TEXT,
            target_full TEXT,
            offered_full TEXT,
            offered_names TEXT,
            value_metrics TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            id TEXT PRIMARY KEY,
            type TEXT,
            owner TEXT,
            target_name TEXT,
            league TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def load_persisted_state():
    """Charge l'historique et les blacklists depuis la DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM trade_history")
    trades = []
    for row in cursor.fetchall():
        trades.append({
            "id": row[0],
            "date": row[1],
            "status": row[2],
            "league": row[3],
            "owner": row[4],
            "target_id": row[5],
            "target_name": row[6],
            "target_full": row[7],
            "offered_full": row[8],
            "offered_names": row[9].split(";;") if row[9] else [],
            "value_metrics": row[10]
        })

    cursor.execute("SELECT * FROM blacklist")
    blacklisted_owners = set()
    blacklisted_targets = set()
    for row in cursor.fetchall():
        if row[1] == "owner":
            blacklisted_owners.add(row[2])
        elif row[1] == "target":
            blacklisted_targets.add((row[3], row[4], row[2]))

    conn.close()
    return trades, blacklisted_owners, blacklisted_targets

if "trade_history" not in st.session_state:
    t_hist, b_owners, b_targets = load_persisted_state()
    st.session_state["trade_history"] = t_hist
    st.session_state["blacklisted_owners"] = b_owners
    st.session_state["blacklisted_targets"] = b_targets

def add_trade_to_db(trade):
    conn = get_db_connection()
    cursor = conn.cursor()
    offered_str = ";;".join(trade.get("offered_names", []))
    cursor.execute("""
        INSERT OR REPLACE INTO trade_history 
        (id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names, value_metrics)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade["id"], trade["date"], trade["status"], trade["league"], trade["owner"],
        trade.get("target_id", ""), trade["target_name"], trade["target_full"],
        trade["offered_full"], offered_str, trade.get("value_metrics", "")
    ))
    conn.commit()
    conn.close()

def update_trade_status_in_db(trade_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE trade_history SET status = ? WHERE id = ?", (status, trade_id))
    conn.commit()
    conn.close()

def delete_all_trades_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trade_history")
    conn.commit()
    conn.close()

def add_to_blacklist_db(item_id, item_type, owner, target_name="", league=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO blacklist (id, type, owner, target_name, league)
        VALUES (?, ?, ?, ?, ?)
    """, (item_id, item_type, owner, target_name, league))
    conn.commit()
    conn.close()

def remove_from_blacklist_db(item_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blacklist WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

# --- APPELS API SLEEPER & VALORISATION ---
@st.cache_data(ttl=86400)
def load_sleeper_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else {}

@st.cache_data(ttl=3600)
def fetch_user_leagues(user_id, year):
    url = f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{year}"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

@st.cache_data(ttl=3600)
def fetch_league_rosters(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

@st.cache_data(ttl=3600)
def fetch_league_users(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    res = requests.get(url)
    if res.status_code == 200:
        return {u["user_id"]: u.get("display_name", u.get("username", "Inconnu")) for u in res.json()}
    return {}

@st.cache_data(ttl=3600)
def fetch_league_draft_info(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/drafts"
    res = requests.get(url)
    roster_to_slot = {}
    completed_seasons = set()
    if res.status_code == 200:
        drafts = res.json()
        for d in drafts:
            if d.get("status") == "complete":
                completed_seasons.add(str(d.get("season")))
            draft_id = d.get("draft_id")
            if draft_id:
                picks_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
                if picks_res.status_code == 200:
                    for p in picks_res.json():
                        if p.get("round") == 1:
                            roster_to_slot[p.get("roster_id")] = p.get("draft_slot")
    return roster_to_slot, completed_seasons

@st.cache_data(ttl=3600)
def fetch_league_traded_picks(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/traded_picks"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

def get_asset_value(rank):
    """Calcul exponentiel de la valeur de trade basée sur le rang ADP."""
    if not rank or rank >= 9000:
        return 100
    val = 10000 * math.exp(-0.018 * (rank - 1))
    return max(int(val), 50)

def calculate_pick_rank_and_label(season, rd, orig_id, my_roster_id, roster_to_slot, total_teams, orig_pseudo, current_year):
    is_current = (season == current_year)
    slot = roster_to_slot.get(orig_id)

    if is_current and slot is not None:
        estimated_pick_pos = slot
        tier_label = f"Pick {season} #{rd}.{slot:02d}"
    else:
        if orig_id == my_roster_id:
            estimated_pick_pos = max(1, int(total_teams * 0.75))
            tier_label = f"Pick {season} Mid/Late {rd}st" if rd == 1 else f"Pick {season} Mid/Late {rd}nd"
        else:
            estimated_pick_pos = max(1, int(total_teams * 0.35))
            tier_label = f"Pick {season} Early/Mid {rd}st" if rd == 1 else f"Pick {season} Early/Mid {rd}nd"

    if rd == 1:
        base_rank = 15
    elif rd == 2:
        base_rank = 45
    elif rd == 3:
        base_rank = 75
    else:
        base_rank = 110

    rank_val = base_rank + (estimated_pick_pos - 1) * 2
    if not is_current:
        rank_val += 12

    label = f"🎟️ {tier_label} (@{orig_pseudo}) [Rank #{rank_val}]"
    pick_name = f"Pick {season} Rd {rd} (@{orig_pseudo})"
    return rank_val, label, pick_name

def save_trade_callback(select_key, trade_entry):
    st.session_state["trade_history"].append(trade_entry)
    add_trade_to_db(trade_entry)
    st.session_state[select_key] = []
    st.toast("Proposition enregistrée avec succès !", icon="📌")

# --- FONCTIONS ALGORITHME UPGRADE PURE ---

def parse_roster_requirements(roster_positions):
    """Compte le nombre de starters requis par poste dans la ligue."""
    counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "SUPER_FLEX": 0}
    if not roster_positions:
        return {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "SUPER_FLEX": 0}
        
    for pos in roster_positions:
        if pos in counts:
            counts[pos] += 1
        elif pos in ["REC_FLEX", "WRRB_FLEX"]:
            counts["FLEX"] += 1
            
    return counts

def is_pure_upgrade(my_group_a_roster, target_player, reqs):
    """
    Simule le lineup titulaire avec uniquement les joueurs du Groupe A.
    Retourne True si la cible apporte une réelle plus-value (comble un trou ou upgrade un starter).
    """
    t_pos = target_player.get("target_pos")
    
    # Ignorer le filtre (conserver le joueur) si la position n'est pas dans QB, RB, WR, TE
    if t_pos not in ["QB", "RB", "WR", "TE"]:
        return True

    t_rank = target_player.get("target_rank", 9999)

    # Séparation de mon Groupe A par poste (triés par rang ADP croissant)
    my_by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in my_group_a_roster:
        pos = p.get("position")
        if pos in my_by_pos:
            my_by_pos[pos].append(p.get("search_rank", 9999))
            
    for pos in my_by_pos:
        my_by_pos[pos].sort()

    # 1. Vérification aux postes stricts (QB, RB, WR, TE)
    needed_strict = reqs.get(t_pos, 0)
    current_strict = my_by_pos[t_pos][:needed_strict]
    
    # Cas A : Le quota strict n'est pas rempli par le Groupe A -> BESOIN DIRECT
    if len(current_strict) < needed_strict:
        return True
        
    # Cas B : Upgrade direct du moins bon starter strict du Groupe A
    if current_strict and t_rank < (current_strict[-1] - 15):
        return True

    # 2. Vérification sur les slots Flex (RB/WR/TE) si pas retenu en strict
    flex_candidates = []
    for pos in ["RB", "WR", "TE"]:
        start_idx = reqs.get(pos, 0)
        flex_candidates.extend(my_by_pos[pos][start_idx:])
    flex_candidates.sort()
    
    needed_flex = reqs.get("FLEX", 0)
    current_flex = flex_candidates[:needed_flex]
    
    if t_pos in ["RB", "WR", "TE"]:
        if len(current_flex) < needed_flex:
            return True
        if current_flex and t_rank < (current_flex[-1] - 15):
            return True

    # 3. Superflex (QB/RB/WR/TE)
    sf_candidates = []
    sf_candidates.extend(my_by_pos["QB"][reqs.get("QB", 0):])
    for pos in ["RB", "WR", "TE"]:
        start_idx = reqs.get(pos, 0) + (1 if pos in ["RB", "WR", "TE"] and len(my_by_pos[pos]) > reqs.get(pos, 0) else 0)
        sf_candidates.extend(my_by_pos[pos][start_idx:])
    sf_candidates.sort()
    
    needed_sf = reqs.get("SUPER_FLEX", 0)
    current_sf = sf_candidates[:needed_sf]
    
    if len(current_sf) < needed_sf:
        return True
    if current_sf and t_rank < (current_sf[-1] - 15):
        return True

    # Si aucune condition d'upgrade/besoin n'est remplie -> MASQUER
    return False


# --- FONCTION PRINCIPALE DE CALCUL ---
@st.cache_data(ttl=600)
def compute_all_data_and_opportunities(
    user_id, year, threshold_a, accepted_trades_tuple=()
):
    all_players = load_sleeper_players()
    leagues = fetch_user_leagues(user_id, year)

    if not leagues:
        return None, None, None, [], [], {}, {}

    league_name_to_id = {l["name"]: l["league_id"] for l in leagues}
    league_size_map = {
        league["name"]: len(league.get("roster_positions") or [])
        for league in leagues
    }
    league_reqs_map = {
        league["name"]: parse_roster_requirements(league.get("roster_positions"))
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
                for p_id in roster.get("players") or []:
                    user_rosters.append({
                        "player_id": str(p_id),
                        "league_id": l_id,
                        "league_name": league["name"],
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
                "league_name": trade_league,
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
        return None, None, None, [], [], {}, {}

    df_rosters = pd.DataFrame(user_rosters)

    def _get_info(p_id):
        p_info = all_players.get(str(p_id), {})
        return (
            p_info.get("full_name", f"Joueur inconnu ({p_id})"),
            p_info.get("position", "N/A"),
            p_info.get("team", "N/A"),
            p_info.get("search_rank") or 9999,
        )

    df_rosters[["player_name", "position", "team", "search_rank"]] = (
        df_rosters["player_id"].apply(lambda x: pd.Series(_get_info(x)))
    )

    exposure = (
        df_rosters.groupby(["player_id", "player_name", "position", "team", "search_rank"])
        .agg(shares=("league_id", "count"), leagues=("league_name", lambda x: list(x)))
        .reset_index()
    )

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

        roster_id_to_pseudo = {
            r.get("roster_id"): league_users.get(r.get("owner_id"), f"Équipe #{r.get('roster_id')}")
            for r in rosters
        }

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
            b_options_list.append((row["search_rank"], label, row["player_name"]))

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
                            "b_names_map": final_b_names_map,
                        })

    target_opportunities.sort(key=lambda x: x["target_rank"])
    return (
        df_rosters,
        group_a,
        group_b,
        target_opportunities,
        leagues,
        league_size_map,
        league_reqs_map,
    )


# --- SIDEBAR & PARAMÈTRES ---
st.sidebar.header("⚙️ Paramètres")
user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

# BOUTON BASCULE UPGRADE PURE
filter_upgrade_pure = st.sidebar.toggle(
    "🔥 Filtre Upgrade Pure",
    value=False,
    help="Masque les opportunités si tes postes titulaires sont déjà sécurisés par des joueurs du Groupe A."
)

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
    (
        df_rosters,
        group_a,
        group_b,
        target_opportunities,
        leagues,
        league_size_map,
        league_reqs_map,
    ) = compute_all_data_and_opportunities(
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

# EXPANDER EXCLUSION LIGUES
with st.sidebar.expander("🏟️ Exclure des Ligues (Radar)", expanded=False):
    excluded_leagues_input = st.multiselect(
        "Ligues masquées dans le Radar :",
        options=all_league_names,
        default=default_excluded_leagues,
        help="Ligues pré-exclues automatiquement par manque d'assets solides en Groupe B."
    )

# EXPANDER BLACKLIST
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

# --- NAVIGATION ONGLETS 1 & 2 ---
tab1, tab2, tab3 = st.tabs(["⭐ Groupe A (Targets)", "🔄 Groupe B (A Trader)", "🎯 Radar de Trade"])

with tab1:
    st.subheader(f"Joueurs clés (≥ {threshold_group_a} parts) — Triés par ADP")
    col_filter_a, _ = st.columns([1, 2])
    with col_filter_a:
        pos_filter_a = st.selectbox("Filtrer par poste", ["Tous", "QB", "RB", "WR", "TE"], key="filter_a")

    filtered_a = group_a if pos_filter_a == "Tous" else group_a[group_a["position"] == pos_filter_a]
    st.write(f"Total : **{len(filtered_a)}** joueurs")

    for _, row in filtered_a.iterrows():
        rank_str = f"Rank #{row['search_rank']}" if row["search_rank"] < 9000 else "Non classé"
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — *{rank_str}* — **{row['shares']} parts**"):
            for l_name in row["leagues"]:
                is_pending = (row["player_name"], l_name) in pending_target_pairs or (row["player_name"], l_name) in pending_offered_pairs
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
        rank_str = f"Rank #{row['search_rank']}" if row["search_rank"] < 9000 else "Non classé"
        with st.expander(f"**[{row['position']}] {row['player_name']}** ({row['team']}) — *{rank_str}* — **{row['shares']} part(s)**"):
            for l_name in row["leagues"]:
                is_pending = (row["player_name"], l_name) in pending_target_pairs or (row["player_name"], l_name) in pending_offered_pairs
                tag = " :gray[⏳ (Trade en cours)]" if is_pending else ""
                st.markdown(f"• {l_name}{tag}")

# ONGLET 3 : RADAR DE TRADE
with tab3:
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
        group_a_ids_set = set(group_a["player_id"])
        group_a_roster_by_league = {}
        for _, r_row in df_rosters.iterrows():
            if r_row["player_id"] in group_a_ids_set:
                l_name = r_row["league_name"]
                if l_name not in group_a_roster_by_league:
                    group_a_roster_by_league[l_name] = []
                group_a_roster_by_league[l_name].append({
                    "position": r_row["position"],
                    "search_rank": r_row["search_rank"]
                })

        radar_opps = []
        for o in target_opportunities:
            l_name = o["league_name"]
            
            if l_name in excluded_leagues_input:
                continue
            if o["owner_pseudo"] in st.session_state["blacklisted_owners"]:
                continue
            if (o["target_name"], l_name, o["owner_pseudo"]) in st.session_state["blacklisted_targets"]:
                continue
            if (o["target_name"], l_name) in pending_target_pairs:
                continue

            if filter_upgrade_pure:
                my_g_a = group_a_roster_by_league.get(l_name, [])
                reqs = league_reqs_map.get(l_name, {})
                if not is_pure_upgrade(my_g_a, o, reqs):
                    continue

            radar_opps.append(o)

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


