import pandas as pd
import streamlit as st
from sleeper_api import fetch_league_rosters, load_sleeper_players


def render_alerts_tab(leagues, user_id):
    st.subheader("🚨 Alerte Joueurs Inactifs Alignés (Starters)")
    st.caption("Détection des joueurs alignés dans tes compositions de départ qui risquent de ne pas jouer sur TOUTES tes ligues.")

    if not leagues:
        st.info("Aucune donnée de ligue disponible.")
        return

    # Chargement global du dictionnaire des joueurs Sleeper
    players_dict = load_sleeper_players()

    out_starters = []          # Out, IR, PUP, SUS
    doubtful_starters = []     # Doubtful
    questionable_starters = [] # Questionable

    with st.spinner("Analyse des compositions de tes ligues en cours..."):
        for league in leagues:
            league_id = league.get("league_id")
            league_name = league.get("name", "Ligue sans nom")

            # Récupération des rosters de la ligue
            rosters = fetch_league_rosters(league_id)
            user_roster = next((r for r in rosters if r.get("owner_id") == user_id), None)
            if not user_roster:
                continue

            starters = user_roster.get("starters", []) or []

            for p_id in starters:
                if not p_id or p_id == "0":
                    continue

                p_info = players_dict.get(p_id, {})
                status = p_info.get("status", "Active")
                player_name = f"{p_info.get('first_name', '')} {p_info.get('last_name', '')}".strip()
                pos = p_info.get("position", "N/A")
                team = p_info.get("team", "FA")

                row = {
                    "player_id": p_id,
                    "name": f"{player_name} ({pos} - {team})",
                    "league": league_name,
                    "status": status
                }

                if status in ["Out", "IR", "PUP", "SUS"]:
                    out_starters.append(row)
                elif status == "Doubtful":
                    doubtful_starters.append(row)
                elif status == "Questionable":
                    questionable_starters.append(row)

    # Fonction pour créer les matrices Joueurs x Ligues
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
