
import streamlit as st
import requests
from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN

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
            try:
                execute_turso_query([("ALTER TABLE trade_history ADD COLUMN value_metrics TEXT;", [])])
            except Exception:
                pass
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
    """Charge la liste des ligues masquées depuis Turso."""
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
    """Ajoute une ligue masquée dans la BDD Turso."""
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("INSERT OR REPLACE INTO excluded_leagues (league_name) VALUES (?);", [league_name])])
        except Exception as e:
            st.toast(f"Erreur sauvegarde ligue masquée : {e}", icon="⚠️")


def remove_excluded_league_db(league_name):
    """Retire une ligue masquée de la BDD Turso."""
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            execute_turso_query([("DELETE FROM excluded_leagues WHERE league_name = ?;", [league_name])])
        except Exception as e:
            st.toast(f"Erreur retrait ligue masquée : {e}", icon="⚠️")


def save_all_excluded_leagues_db(league_set):
    """Remplace l'ensemble des ligues masquées dans Turso (lors d'un recalcul)."""
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        try:
            statements = [("DELETE FROM excluded_leagues;", [])]
            for lname in league_set:
                statements.append(("INSERT INTO excluded_leagues (league_name) VALUES (?);", [lname]))
            execute_turso_query(statements)
        except Exception as e:
            st.toast(f"Erreur mise à jour globale des ligues masquées : {e}", icon="⚠️")


def add_trade_to_db(trade):
    """Insère un trade avec ses 11 colonnes (incluant value_metrics)."""
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
