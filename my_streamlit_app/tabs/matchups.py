import pandas as pd
import streamlit as st
from sleeper_api import fetch_nfl_schedule
from helpers import get_current_nfl_week


def render_matchups_tab(group_a, group_b, threshold_group_a, season_year="2026"):
    st.subheader("🏈 Matchups NFL & Évolution des Inactifs")

    nfl_schedule = fetch_nfl_schedule(season_year)
    current_week = get_current_nfl_week()

    # Formulaire pour éviter les ré-exécutions à chaque clic dans le multiselect
    with st.form(key="matchups_filter_form"):
        col_w, col_m = st.columns([1, 3])
        
        with col_w:
            sel_week = st.number_input(
                "Semaine NFL",
                min_value=1,
                max_value=18,
                value=current_week,
                step=1,
                key="tab5_week"
            )

        matchups_for_week = nfl_schedule.get(sel_week, [])
        labels_map = {m["label"]: m for m in matchups_for_week} if matchups_for_week else {}
        default_selection = [list(labels_map.keys())[0]] if labels_map else []

        with col_m:
            sel_labels = st.multiselect(
                "Choisir une ou plusieurs rencontres :",
                options=list(labels_map.keys()),
                default=default_selection,
                key="tab5_matchup_select"
            )

        # Bouton de validation pour tout calculer en une seule fois
        submit_btn = st.form_submit_button("🔎 Appliquer / Actualiser la recherche", use_container_width=True)

    if not matchups_for_week:
        st.info(f"Aucune rencontre enregistrée pour la semaine {sel_week}.")
    elif not sel_labels:
        st.info("Veuillez sélectionner au moins une rencontre et cliquer sur **Appliquer**.")
    else:
        # Récupération des équipes uniquement après validation du formulaire
        selected_teams = set()
        for label in sel_labels:
            m_data = labels_map[label]
            selected_teams.add(m_data["away"])
            selected_teams.add(m_data["home"])

        key_players_in_match = group_a[group_a["team"].isin(selected_teams)].copy()

        if key_players_in_match.empty:
            st.info("Aucun joueur du Groupe A ne participe aux rencontres sélectionnées.")
        else:
            leagues_with_players = set()
            for _, p_row in key_players_in_match.iterrows():
                leagues_with_players.update(p_row["leagues"])

            active_cols_leagues = sorted(list(leagues_with_players))
            
            if not active_cols_leagues:
                st.info("Les joueurs clés de ces matchs sont dans des ligues actuellement masquées.")
            else:
                matrix_rows = []
                for _, p_row in key_players_in_match.iterrows():
                    p_leagues_set = set(p_row["leagues"])
                    active_shares_count = len(p_leagues_set.intersection(set(active_cols_leagues)))

                    status_flag = f" [{p_row['status']}]" if p_row.get("status") and p_row["status"] != "Active" else ""
                    row_data = {
                        "Joueurs": f"{p_row['player_name']} ({p_row['position']} - {p_row['team']}){status_flag}",
                        "Ligues (Total)": f"📊 {active_shares_count}"
                    }

                    for lname in active_cols_leagues:
                        row_data[lname] = "🔵" if lname in p_leagues_set else " "

                    matrix_rows.append(row_data)

                df_matrix = pd.DataFrame(matrix_rows)

                matchups_str = ", ".join(sel_labels)
                st.markdown(f"### ⚔️ **{matchups_str}** (Semaine {sel_week})")
                st.dataframe(
                    df_matrix,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Joueurs": st.column_config.Column("Joueurs"),
                        "Ligues (Total)": st.column_config.Column("Ligues (Total)")
                    }
                )

    
