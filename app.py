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

# ==========================================
# 1. BASE DE DONNÉES TURSO (HTTP API v2)
# ==========================================

TURSO_DATABASE_URL = st.secrets.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")

def execute_turso_query(statements):
    """Exécute des requêtes SQL directement via l'API HTTP v2 de Turso."""
    url = TURSO_DATABASE_URL.replace("libsql://", "https://").replace("sqlite://", "https://")
    if not url.endswith("/v2/pipeline"):
        url = url.rstrip("/") + "/v2/pipeline"

    headers = {
        "Authorization": f"Bearer {TURSO_AUTH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    requests_payload = []
    for stmt in statements:
        sql = stmt[0]
        params = stmt[1] if len(stmt) > 1 else []
        
        args = []
        for p in params:
            if isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": p})
            elif p is None:
                args.append({"type": "null"})
            else:
                args.append({"type": "text", "value": str(p)})
                
        requests_payload.append({
            "type": "execute",
            "stmt": {"sql": sql, "args": args}
        })

    response = requests.post(url, json={"requests": requests_payload}, headers=headers, timeout=5)
    response.raise_for_status()
    
    data = response.json()
    results = []
    
    for res in data.get("results", []):
        if res.get("type") == "ok":
            response_obj = res.get("response", {}).get("result", {})
            cols = [c["name"] for c in response_obj.get("cols", [])]
            rows = []
            for r in response_obj.get("rows", []):
                row_vals = []
                for cell in r:
                    if isinstance(cell, dict):
                        row_vals.append(cell.get("value"))
                    else:
                        row_vals.append(cell)
                rows.append(row_vals)
            results.append((cols, rows))
        elif res.get("type") == "error":
            err_msg = res.get("error", {}).get("message", "Erreur Turso inconnue")
            raise Exception(f"SQL Error: {err_msg}")
            
    return results


def init_db():
    """Crée les tables et migre le schéma vers 11 colonnes + table excluded_leagues."""
    st.session_state["db_warning"] = None
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([
                ("""CREATE TABLE IF NOT EXISTS trade_history (
                    id TEXT PRIMARY KEY, date TEXT, status TEXT, league TEXT, owner TEXT,
                    target_id TEXT, target_name TEXT, target_full TEXT, offered_full TEXT,
                    offered_names TEXT, value_metrics TEXT
                );""", []),
                ("""CREATE TABLE IF NOT EXISTS blacklist (
                    id TEXT PRIMARY KEY, type TEXT, owner TEXT, target_name TEXT, league TEXT
                );""", []),
                ("""CREATE TABLE IF NOT EXISTS excluded_leagues (
                    league_name TEXT PRIMARY KEY
                );""", [])
            ])
        except Exception as e:
            st.session_state["db_warning"] = f"Échec de connexion Turso HTTP : {str(e)}"
    else:
        st.session_state["db_warning"] = "Secrets Turso non configurés."


def load_persisted_state():
    """Charge l'historique (11 colonnes) et la blacklist depuis Turso."""
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and not st.session_state.get("db_warning"):
        try:
            res = execute_turso_query([
                ("SELECT id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names, value_metrics FROM trade_history;", []),
                ("SELECT id, type, owner, target_name, league FROM blacklist;", [])
            ])
            
            trades = []
            if res and len(res) > 0:
                cols, rows = res[0]
                for row in rows:
                    if len(row) >= 10:
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
                            "offered_names": str(row[9]).split(";;") if row[9] else [],
                            "value_metrics": row[10] if len(row) >= 11 and row[10] is not None else ""
                        })

            b_owners = set()
            b_targets = set()
            if res and len(res) > 1:
                cols_b, rows_b = res[1]
                for row in rows_b:
                    if len(row) >= 5:
                        if row[1] == "owner":
                            b_owners.add(row[2])
                        elif row[1] == "target":
                            b_targets.add((row[3], row[4], row[2]))

            return trades, b_owners, b_targets
        except Exception as e:
            st.session_state["db_warning"] = f"Erreur lecture Turso : {str(e)}"

    return [], set(), set()


def load_excluded_leagues_db():
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and not st.session_state.get("db_warning"):
        try:
            res = execute_turso_query([("SELECT league_name FROM excluded_leagues;", [])])
            if res and len(res) > 0:
                _, rows = res[0]
                return set(r[0] for r in rows if r)
        except Exception as e:
            st.toast(f"Erreur chargement ligues masquées BDD : {e}", icon="⚠️")
    return set()


def add_excluded_league_db(league_name):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("INSERT OR REPLACE INTO excluded_leagues (league_name) VALUES (?);", [league_name])])
        except Exception as e:
            st.toast(f"Erreur sauvegarde ligue masquée : {e}", icon="⚠️")


def remove_excluded_league_db(league_name):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("DELETE FROM excluded_leagues WHERE league_name = ?;", [league_name])])
        except Exception as e:
            st.toast(f"Erreur retrait ligue masquée : {e}", icon="⚠️")


def save_all_excluded_leagues_db(league_set):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            statements = [("DELETE FROM excluded_leagues;", [])]
            for lname in league_set:
                statements.append(("INSERT INTO excluded_leagues (league_name) VALUES (?);", [lname]))
            execute_turso_query(statements)
        except Exception as e:
            st.toast(f"Erreur mise à jour globale des ligues masquées : {e}", icon="⚠️")


def add_trade_to_db(trade):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            offered_str = ";;".join(trade.get("offered_names", []))
            sql = """INSERT OR REPLACE INTO trade_history 
                     (id, date, status, league, owner, target_id, target_name, target_full, offered_full, offered_names, value_metrics)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"""
            params = [
                trade["id"], trade["date"], trade["status"], trade["league"], trade["owner"],
                trade.get("target_id", ""), trade["target_name"], trade["target_full"],
                trade["offered_full"], offered_str, trade.get("value_metrics", "")
            ]
            execute_turso_query([(sql, params)])
        except Exception as e:
            st.toast(f"Erreur sauvegarde BDD : {e}", icon="⚠️")


def update_trade_status_in_db(trade_id, status):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("UPDATE trade_history SET status = ? WHERE id = ?;", [status, trade_id])])
        except Exception as e:
            st.toast(f"Erreur mise à jour BDD : {e}", icon="⚠️")


def delete_all_trades_db():
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("DELETE FROM trade_history;", [])])
        except Exception as e:
            st.toast(f"Erreur suppression BDD : {e}", icon="⚠️")


def add_to_blacklist_db(item_id, item_type, owner, target_name="", league=""):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            sql = "INSERT OR REPLACE INTO blacklist (id, type, owner, target_name, league) VALUES (?, ?, ?, ?, ?);"
            execute_turso_query([(sql, [item_id, item_type, owner, target_name, league])])
        except Exception as e:
            st.toast(f"Erreur blacklist BDD : {e}", icon="⚠️")


def remove_from_blacklist_db(item_id):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("DELETE FROM blacklist WHERE id = ?;", [item_id])])
        except Exception as e:
            st.toast(f"Erreur retrait blacklist : {e}", icon="⚠️")

# ==========================================
# 2. INITIALISATION ET HELPERS
# ==========================================

init_db()

if "trade_history" not in st.session_state:
    t_hist, b_owners, b_targets = load_persisted_state()
    st.session_state["trade_history"] = t_hist
    st.session_state["blacklisted_owners"] = b_owners
    st.session_state["blacklisted_targets"] = b_targets

if st.session_state.get("db_warning"):
    st.error(f"⚠️ **Alerte BDD Turso :** {st.session_state['db_warning']}")


def get_league_format_badge(roster_positions, league_settings):
    """Génère le badge émoji selon le format (ex: ⚡🏰 SF Dynasty)."""
    roster_pos = roster_positions or []
    is_sf = "SUPER_FLEX" in roster_pos or roster_pos.count("QB") >= 2
    is_dynasty = league_settings.get("type") != 0
    
    qb_icon = "⚡" if is_sf else "🎯"
    type_icon = "🏰" if is_dynasty else "🔄"
    
    qb_label = "SF" if is_sf else "1QB"
    type_label = "Dynasty" if is_dynasty else "Redraft"
    
    return f"{qb_icon}{type_icon} {qb_label} {type_label}"


def get_adjusted_player_rank(p_info, is_superflex=True, is_dynasty=True):
    """Ajuste l'ADP Redraft 1QB brut de Sleeper pour refléter la valeur SF/Dynasty."""
    raw_rank = p_info.get("search_rank") or 9999
    pos = p_info.get("position")
    age = p_info.get("age") or 25

    if pos == "QB":
        if is_superflex:
            raw_rank = max(1, int(raw_rank * 0.35))
        else:
            raw_rank = int(raw_rank * 1.5)
    elif pos == "TE":
        raw_rank = int(raw_rank * 0.9)

    if is_dynasty:
        if age <= 23:
            raw_rank = int(raw_rank * 0.85)
        elif age >= 29 and pos in ["RB", "WR"]:
            raw_rank = int(raw_rank * 1.30)

    return raw_rank


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
        tier_label = f"Pick {season} #{rd}.{slot:02d}"
        estimated_pick_pos = slot
    else:
        if orig_id == my_roster_id:
            estimated_pick_pos = max(1, int(total_teams * 0.75))
            tier_label = f"Pick {season} Mid/Late {rd}st" if rd == 1 else f"Pick {season} Mid/Late {rd}nd"
        else:
            estimated_pick_pos = max(1, int(total_teams * 0.35))
            tier_label = f"Pick {season} Early/Mid {rd}st" if rd == 1 else f"Pick {season} Early/Mid {rd}nd"

    base_rank = {1: 15, 2: 45, 3: 75}.get(rd, 110)

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


# ==========================================
# 3. APPELS API SLEEPER CACHÉS
# ==========================================

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
    is_upcoming_draft_done = True
    
    if res.status_code == 200:
        drafts = res.json()
        for d in drafts:
            status = d.get("status")
            if status == "complete":
                completed_seasons.add(str(d.get("season")))
            else:
                is_upcoming_draft_done = False

            draft_id = d.get("draft_id")
            if draft_id:
                picks_res = requests.get(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
                if picks_res.status_code == 200:
                    for p in picks_res.json():
                        if p.get("round") == 1:
                            roster_to_slot[p.get("roster_id")] = p.get("draft_slot")
                            
    return roster_to_slot, completed_seasons, is_upcoming_draft_done

@st.cache_data(ttl=3600)
def fetch_league_traded_picks(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/traded_picks"
    res = requests.get(url)
    return res.json() if res.status_code == 200 else []

# ==========================================
# 4. INTERFACE UTILISATEUR & FILTRES
# ==========================================

st.title("🏈 Empire Trade Radar")

with st.sidebar:
    st.header("⚙️ Configuration")
    username = st.text_input("Nom d'utilisateur Sleeper", value="")
    season_year = st.selectbox("Saison", [2026, 2025, 2024], index=0)
    
    st.divider()
    st.subheader("🎯 Filtres des Cibles (Groupe A)")
    target_positions = st.multiselect("Positions ciblées", ["QB", "RB", "WR", "TE"], default=["QB", "RB", "WR", "TE"])
    max_target_rank = st.slider("Rang max du joueur ciblé", 1, 300, 150)
    
    st.divider()
    st.subheader("💼 Filtres des Monnaies (Groupe B)")
    allow_picks = st.checkbox("Inclure les Picks de Draft", value=True)
    max_offered_rank = st.slider("Rang max des joueurs à offrir", 1, 400, 250)

# Récupération de l'utilisateur Sleeper
user_data = None
if username:
    u_res = requests.get(f"https://api.sleeper.app/v1/user/{username}")
    if u_res.status_code == 200:
        user_data = u_res.json()
    else:
        st.error("Utilisateur Sleeper introuvable.")

if not user_data:
    st.info("👈 Veuillez entrer votre nom d'utilisateur Sleeper dans le panneau latéral pour commencer.")
    st.stop()

my_user_id = user_data["user_id"]
all_players = load_sleeper_players()
leagues = fetch_user_leagues(my_user_id, str(season_year))

if not leagues:
    st.warning(f"Aucune ligue trouvée pour {username} en {season_year}.")
    st.stop()

# Chargement des ligues masquées enregistrées
if "excluded_leagues" not in st.session_state:
    st.session_state["excluded_leagues"] = load_excluded_leagues_db()

active_leagues = [l for l in leagues if l["name"] not in st.session_state["excluded_leagues"]]

st.success(f" Connecté : **{username}** | **{len(active_leagues)}** / **{len(leagues)}** ligues actives")

# ==========================================
# 5. MOTEUR D'ANALYSE ET AFFICHAGE TABLEAU
# ==========================================

trade_opportunities = []

for league in active_leagues:
    l_id = league["league_id"]
    l_name = league["name"]
    rosters = fetch_league_rosters(l_id)
    users_map = fetch_league_users(l_id)
    badge = get_league_format_badge(league.get("roster_positions"), league.get("settings", {}))
    
    my_roster = next((r for r in rosters if r.get("owner_id") == my_user_id), None)
    if not my_roster:
        continue
        
    my_roster_id = my_roster["roster_id"]
    my_players_ids = set(my_roster.get("players") or [])
    
    # Construction du Groupe B (Monnaies d'échange)
    my_b_assets = []
    for pid in my_players_ids:
        p_info = all_players.get(pid, {})
        rank = get_adjusted_player_rank(p_info)
        if rank <= max_offered_rank:
            val = get_asset_value(rank)
            p_name = f"{p_info.get('full_name', pid)} ({p_info.get('position')})"
            my_b_assets.append({"id": pid, "name": p_name, "rank": rank, "value": val, "type": "player"})
            
    # Analyse des rosters adverses
    for opponent in rosters:
        opp_owner_id = opponent.get("owner_id")
        if not opp_owner_id or opp_owner_id == my_user_id:
            continue
            
        opp_pseudo = users_map.get(opp_owner_id, "Adversaire")
        
        # Vérification Blacklist
        if opp_pseudo in st.session_state.get("blacklisted_owners", set()):
            continue
            
        opp_players = opponent.get("players") or []
        for pid in opp_players:
            p_info = all_players.get(pid, {})
            pos = p_info.get("position")
            
            if pos not in target_positions:
                continue
                
            rank = get_adjusted_player_rank(p_info)
            if rank <= max_target_rank:
                target_name = p_info.get("full_name", pid)
                
                # Vérification Blacklist Cible
                if (target_name, l_name, opp_pseudo) in st.session_state.get("blacklisted_targets", set()):
                    continue
                    
                target_val = get_asset_value(rank)
                
                # Recherche d'équivalences de valeur dans le Groupe B
                matching_b = [
                    b for b in my_b_assets 
                    if abs(b["value"] - target_val) / max(target_val, 1) <= 0.25
                ]
                
                for b_match in matching_b:
                    diff_pct = round(((b_match["value"] - target_val) / target_val) * 100, 1)
                    diff_str = f"+{diff_pct}%" if diff_pct > 0 else f"{diff_pct}%"
                    
                    trade_opportunities.append({
                        "Cible (Joueur)": f"{target_name} ({pos})",
                        "Ligue": l_name,
                        "Format": badge,
                        "Propriétaire": f"@{opp_pseudo}",
                        "Monnaie Proposée": b_match["name"],
                        "Valeur Cible": target_val,
                        "Valeur Monnaie": b_match["value"],
                        "Écart Value": diff_str,
                        "Rank Cible": f"#{rank}",
                        "Rank Monnaie": f"#{b_match['rank']}"
                    })

# --- AFFICHAGE AVEC COLONNE FIGÉE ---
st.subheader("⚡ Opportunités de Trades Détectées")

if trade_opportunities:
    df_trades = pd.DataFrame(trade_opportunities)
    
    # 📌 POSE DE LA COLONNE FIGÉE EN INDEX :
    # Définir 'Cible (Joueur)' comme index la fige automatiquement tout à gauche lors du scroll horizontal
    df_display = df_trades.set_index("Cible (Joueur)")
    
    st.dataframe(
        df_display,
        use_container_width=True,
        height=500
    )
    st.caption("💡 *Astuce : La première colonne 'Cible (Joueur)' est figée à gauche lors du défilement horizontal.*")
else:
    st.info("Aucune opportunité trouvée avec les filtres actuels. Essayez d'élargir les rangs ADP dans le panneau latéral.")
