import pandas as pd
import streamlit as st
from sleeper_api import fetch_league_rosters, load_sleeper_players


def render_alerts_tab(leagues, user_id):
    st.subheader("🚨 Alerte Joueurs Inactifs Alignés (Starters)")
    st.caption("Détection des joueurs alignés dans tes compositions de départ qui risquent de ne pas jouer sur TOUTES tes ligues.")

    if not leagues:
        st.info("Aucune donnée de ligue disponible.")
        return

    col_btn, col_debug = st.columns([1, 2])
    with col_btn:
        if st.button("🔄 Rafraîchir l'analyse des Starters", use_container_width=True):
            fetch_league_rosters.clear()
            st.toast("Composition des rosters rafraîchie avec succès !", icon="✅")

    with col_debug:
        debug_mode = st.checkbox("🔍 Activer le mode débogage (Inspection des IDs & Statuts)")

    players_dict = load_sleeper_players()

    out_starters = []          # Out, IR, PUP, SUS
    doubtful_starters = []     # Doubtful
    questionable_starters = [] # Questionable

    user_id_str = str(user_id)
    debug_logs = []

    with st.spinner("Analyse des compositions de tes ligues en cours..."):
        for league in leagues:
            league_id = league.get("league_id")
            league_name = league.get("name", "Ligue sans nom")

            rosters = fetch_league_rosters(league_id)
            if not rosters:
                continue

            # Recherche du roster utilisateur
            user_roster = None
            for r in rosters:
                owner_id = str(r.get("owner_id")) if r.get("owner_id") else None
                co_owners = [str(co) for co in (r.get("co_owners") or [])]
                
                if owner_id == user_id_str or user_id_str in co_owners:
                    user_roster = r
                    break

            if not user_roster:
                if debug_mode:
                    debug_logs.append(f"❌ Roster introuvable pour la ligue : **{league_name}** (User ID recherché: `{user_id_str}`)")
                continue

            starters = user_roster.get("starters", []) or []

            for p_id in starters:
                if not p_id or str(p_id) == "0":
                    continue

                p_str_id = str(p_id)
                p_info = players_dict.get(p_str_id, {})

                # Récupération croisée du statut (status vs injury_status)
                status = p_info.get("injury_status") or p_info.get("status") or "Active"
                player_name = f"{p_info.get('first_name', '')} {p_info.get('last_name', '')}".strip()
                pos = p_info.get("position", "N/A")
                team = p_info.get("team", "FA")

                if debug_mode:
                    debug_logs.append(f"🏈 Ligue: **{league_name}** | Joueur: `{player_name}` (`{p_str_id}`) | Statut détecté: `{status}`")

                row = {
                    "player_id": p_str_id,
                    "name": f"{player_name} ({pos} - {team})",
                    "league": league_name,
                    "status": status
                }

                # Normalisation de la casse pour la détection
                status_upper = str(status).upper()

                if any(s in status_upper for s in ["OUT", "IR", "PUP", "SUS", "DOUBTFUL"]):
                    if "DOUBTFUL" in status_upper:
                        doubtful_starters.append(row)
                    else:
                        out_starters.append(row)
                elif "QUESTIONABLE" in status_upper or "QUESTION" in status_upper or status_upper == "Q":
                    questionable_starters.append(row)

    # Affichage des logs si le mode débogage est activé
    if debug_mode and debug_logs:
        with st.expander("🛠️ Logs d'inspection de l'API Sleeper", expanded=True):
            for log in debug_logs:
                st.write(log)

    def build_alert_matrix(data_list):
        if not data_list:
            return None

        df = pd.DataFrame(data_list)
        pivot_df = df.pivot_table(
            index="name",
            columns="league",
            aggfunc="size",
            fill_value=0
        )

        matrix_rows = []
        for player, row in pivot_df.iterrows():
            total_starters = row.sum()
            row_dict = {
                "Joueurs Starters": player,
                "Ligues affectées": f"🔴 {total_starters}"
            }
            for league_col in pivot_df.columns:
                row_dict[league_col] = "🚨 ALIGNÉ" if row[league_col] > 0 else " "
            matrix_rows.append(row_dict)

        return pd.DataFrame(matrix_rows)

    # --- TABLEAU 1 : INACTIFS CONFIRMÉS ---
    st.markdown("### 🛑 1. Urgence Absolue — Inactifs Confirmés (Out / IR / PUP / SUS)")
    df_out = build_alert_matrix(out_starters)
    if df_out is not None:
        st.dataframe(df_out, use_container_width=True, hide_index=True)
    else:
        st.success("✅ Aucun joueur inactif confirmé n'est aligné dans tes starters !")

    st.markdown("---")

    # --- TABLEAU 2 : DOUBTFUL ---
    st.markdown("### ⚠️ 2. Très Incertains (Doubtful)")
    df_doubtful = build_alert_matrix(doubtful_starters)
    if df_doubtful is not None:
        st.dataframe(df_doubtful, use_container_width=True, hide_index=True)
    else:
        st.success("✅ Aucun starter en statut Doubtful.")

    st.markdown("---")

    # --- TABLEAU 3 : QUESTIONABLE ---
    st.markdown("### 🟧 3. À surveiller (Questionable)")
    df_quest = build_alert_matrix(questionable_starters)
    if df_quest is not None:
        st.dataframe(df_quest, use_container_width=True, hide_index=True)
    else:
        st.info("Aucun starter en statut Questionable.")
