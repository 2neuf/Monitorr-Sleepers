import streamlit as st
import requests
import json
from datetime import datetime

# ==========================================
# CONFIGURATION DE LA PAGE
# ==========================================
st.set_page_config(page_title="Sleeper Trade Scout", layout="wide", page_icon="🏈")
st.title("🏈 Sleeper Trade Scout & Roster Optimization")

# Secrets Streamlit
TURSO_DATABASE_URL = st.secrets.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = st.secrets.get("TURSO_AUTH_TOKEN", "")

# ==========================================
# 1. BASE DE DONNÉES TURSO (HTTP API v2)
# ==========================================
def execute_turso_query(statements):
    """Exécute des requêtes SQL via l'API HTTP v2 de Turso."""
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

    response = requests.post(url, json={"requests": requests_payload}, headers=headers, timeout=8)
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
    """Initialise les tables Turso et applique les migrations (11 colonnes)."""
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
                );""", [])
            ])
            try:
                execute_turso_query([("ALTER TABLE trade_history ADD COLUMN value_metrics TEXT;", [])])
            except Exception:
                pass
        except Exception as e:
            st.session_state["db_warning"] = f"Échec BDD Turso : {str(e)}"
    else:
        st.session_state["db_warning"] = "Secrets Turso non configurés."

def load_persisted_state():
    """Charge l'historique et la blacklist depuis Turso."""
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
                            "id": row[0], "date": row[1], "status": row[2], "league": row[3],
                            "owner": row[4], "target_id": row[5], "target_name": row[6],
                            "target_full": row[7], "offered_full": row[8],
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

def add_to_blacklist_db(item_id, item_type, owner, target_name="", league=""):
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            sql = "INSERT OR REPLACE INTO blacklist (id, type, owner, target_name, league) VALUES (?, ?, ?, ?, ?);"
            execute_turso_query([(sql, [item_id, item_type, owner, target_name, league])])
        except Exception as e:
            st.toast(f"Erreur blacklist BDD : {e}", icon="⚠️")

init_db()
if "trade_history" not in st.session_state:
    t_hist, b_owners, b_targets = load_persisted_state()
    st.session_state["trade_history"] = t_hist
    st.session_state["blacklisted_owners"] = b_owners
    st.session_state["blacklisted_targets"] = b_targets

# ==========================================
# 2. CHARGEMENT API SLEEPER / KTC (CACHÉ)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_sleeper_data(username, season="2026"):
    """Récupère l'user, ses ligues et les détails des rosters."""
    user_res = requests.get(f"https://api.sleeper.app/v1/user/{username}").json()
    if not user_res:
        return None, []
    user_id = user_res["user_id"]
    leagues = requests.get(f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{season}").json()
    return user_id, leagues

@st.cache_data(ttl=3600)
def fetch_league_rosters(league_id):
    rosters = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/rosters").json()
    users = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users").json()
    league_details = requests.get(f"https://api.sleeper.app/v1/league/{league_id}").json()
    
    user_dict = {u["user_id"]: u.get("display_name", u["user_id"]) for u in users}
    return rosters, user_dict, league_details.get("roster_positions", [])

# ==========================================
# 3. FILTRES D'OPTIMISATION DE ROSTER
# ==========================================

def passes_upgrade_pure(target_player, user_roster, league_slots):
    """
    Filtre Upgrade Pure : Propose le joueur si sa valeur dépasse 
    strictement celle du meilleur joueur du même poste dans le roster.
    """
    pos = target_player.get("position")
    roster_pos = [p for p in user_roster if p.get("position") == pos]
    if not roster_pos:
        return True
    
    is_sf = "SUPER_FLEX" in league_slots or league_slots.count("QB") >= 2
    val_key = "val_sf" if is_sf else "val_1qb"
    
    target_val = target_player.get(val_key, 0)
    best_roster_val = max([p.get(val_key, 0) for p in roster_pos])
    
    return target_val > best_roster_val

def passes_trade_urgent_no_flex(target_player, user_roster, league_slots):
    """
    Filtre Trade Urgent (Sans FLEX) : Évalue la cible par rapport
    au pire titulaire STRICT de son poste dans le lineup.
    """
    pos = target_player.get("position")
    roster_pos = [p for p in user_roster if p.get("position") == pos]
    
    strict_slots_count = league_slots.count(pos)
    if strict_slots_count == 0:
        strict_slots_count = 1
        
    if len(roster_pos) < strict_slots_count:
        return True
        
    is_sf = "SUPER_FLEX" in league_slots or league_slots.count("QB") >= 2
    val_key = "val_sf" if is_sf else "val_1qb"
    
    sorted_roster = sorted(roster_pos, key=lambda x: x.get(val_key, 0), reverse=True)
    cutoff_starter = sorted_roster[strict_slots_count - 1]
    cutoff_val = cutoff_starter.get(val_key, 0)
    target_val = target_player.get(val_key, 0)
    
    # Ratios exigés selon le statut du poste
    if pos == "QB" and not is_sf:
        min_ratio = 1.35
    elif pos == "QB" and is_sf:
        min_ratio = 1.20
    else:
        min_ratio = 1.25
        
    return target_val >= (cutoff_val * min_ratio)

def precalculate_candidates(all_targets, user_roster, league_slots):
    """Pré-calcule les flags de filtrage une seule fois au chargement."""
    candidates = []
    for target in all_targets:
        is_pure = passes_upgrade_pure(target, user_roster, league_slots)
        is_urgent = passes_trade_urgent_no_flex(target, user_roster, league_slots)
        candidates.append({
            "player": target,
            "is_pure": is_pure,
            "is_urgent": is_urgent
        })
    return candidates

# ==========================================
# 4. SIDEBAR ET RECHERCHE
# ==========================================
st.sidebar.header("⚙️ Configuration")
sleeper_user = st.sidebar.text_input("Nom d'utilisateur Sleeper", value="")

use_upgrade_pure = st.sidebar.checkbox("Filtre Upgrade Pure", value=False)
use_trade_urgent = st.sidebar.checkbox("Filtre Trade Urgent (No Flex)", value=False)

if st.session_state.get("db_warning"):
    st.sidebar.warning(st.session_state["db_warning"])

# ==========================================
# 5. EXECUTION & DISPLAY
# ==========================================
if sleeper_user:
    user_id, leagues = fetch_sleeper_data(sleeper_user)
    
    if not leagues:
        st.warning("Aucune ligue trouvée pour cet utilisateur.")
    else:
        league_names = [l["name"] for l in leagues]
        selected_league_name = st.selectbox("Sélectionnez votre ligue", league_names)
        selected_league = next(l for l in leagues if l["name"] == selected_league_name)
        
        league_id = selected_league["league_id"]
        rosters, user_dict, league_slots = fetch_league_rosters(league_id)
        
        user_roster_data = next((r for r in rosters if r["owner_id"] == user_id), None)
        
        if user_roster_data:
            # Construction indicative des joueurs (à lier avec tes structures de players/values)
            st.sidebar.success(f"Ligue chargée : {selected_league['name']}")
            
            # Exemple de structure pour illustrer le pré-calcul
            # Remplace 'targets_data' et 'user_roster' avec tes dictionnaires d'assets enrichis (val_sf, val_1qb, position...)
            if "candidates_cache" not in st.session_state or st.sidebar.button("🔄 Rafraîchir les candidats"):
                # Simulation de données targets & user_roster
                sample_targets = []
                sample_user_roster = []
                
                # Exécution du pré-calcul rapide
                st.session_state["candidates_cache"] = precalculate_candidates(
                    sample_targets, sample_user_roster, league_slots
                )
            
            # Filtrage dynamique instantané
            raw_candidates = st.session_state.get("candidates_cache", [])
            filtered_targets = []
            
            for item in raw_candidates:
                if use_upgrade_pure and not item["is_pure"]:
                    continue
                if use_trade_urgent and not item["is_urgent"]:
                    continue
                filtered_targets.append(item["player"])
                
            st.subheader("🎯 Radar d'Opportunités de Trade")
            st.metric("Total Opportunités Qualifiées", len(filtered_targets))
            
            if filtered_targets:
                st.dataframe(filtered_targets)
            else:
                st.info("Aucune opportunité ne correspond aux critères de filtres actuellement sélectionnés.")
else:
    st.info("Entrez votre pseudo Sleeper dans la barre latérale pour commencer.")
