import streamlit as st
import pandas as pd
from config import get_nfl_schedule_2026
from sleeper_api import fetch_nfl_schedule
import streamlit as st
from sleeper_api import fetch_full_nfl_schedule
from helpers import get_current_nfl_week  # ou depuis sleeper_api selon où tu l'as mise

def render_matchups_tab(group_a, group_b, excluded_leagues_input, threshold_group_a, season_year="2026"):
    st.subheader("🏈 Matchups NFL & Évolution des Inactifs")
    st.caption("Sélectionne une ou plusieurs semaines / rencontres pour additionner les joueurs concernés.")

    # 1. Chargement instantané de toute la saison via le cache
    full_schedule = fetch_full_nfl_schedule(season_year)

    # 2. Détermination de la semaine courante automatique
    current_week = get_current_nfl_week()

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

    # Récupération des matchs de la semaine sélectionnée
    available_matchups = full_schedule.get(sel_week, [])
    matchup_options = [m["label"] for m in available_matchups]

    with col_m:
        # Sélection multiple de rencontres (par défaut : toutes les rencontres de la semaine)
        selected_matchup_labels = st.multiselect(
            "Rencontres à analyser",
            options=matchup_options,
            default=matchup_options,
            key="tab5_matchups_multiselect"
        )

    # 3. Fusion et extraction de toutes les équipes impliquées dans les matchs sélectionnés
    selected_teams = set()
    for m in available_matchups:
        if m["label"] in selected_matchup_labels:
            selected_teams.add(m["away"])
            selected_teams.add(m["home"])

    # 4. Filtrage de tes joueurs (Groupes A / B) sur l'ensemble des équipes retenues
    # Il te suffit d'utiliser 'selected_teams' pour filtrer ton tableau ou tes cartes de joueurs !


def render_matchups_tab(group_a, group_b, excluded_leagues_input, threshold_group_a, season_year="2026"):
    st.subheader("🏈 Matchups NFL & Évolution des Inactifs")
    
    col_w, _ = st.columns([1, 3])
    with col_w:
        sel_week = st.number_input("Semaine NFL", min_value=1, max_value=18, value=1, step=1, key="tab5_week")

    nfl_schedule = fetch_nfl_schedule(season_year)
    matchups_for_week = nfl_schedule.get(sel_week, [])
    
    if not matchups_for_week:
        st.info(f"Aucune rencontre enregistrée pour la semaine {sel_week}.")
    else:
        labels_map = {m["label"]: m for m in matchups_for_week}
        sel_label = st.selectbox("Choisir une rencontre :", options=list(labels_map.keys()), key="tab5_matchup_select")

        matchup_data = labels_map[sel_label]
        away_t = matchup_data["away"]
        home_t = matchup_data["home"]

        key_players_in_match = group_a[group_a["team"].isin([away_t, home_t])].copy()

        if key_players_in_match.empty:
            st.info(f"Aucun joueur du Groupe A ne participe au match **{sel_label}**.")
        else:
            leagues_with_players = set()
            for _, p_row in key_players_in_match.iterrows():
                leagues_with_players.update(p_row["leagues"])

            active_cols_leagues = sorted([
                lname for lname in leagues_with_players 
                if lname not in excluded_leagues_input
            ])

            if not active_cols_leagues:
                st.info("Les joueurs clés de ce match sont dans des ligues actuellement masquées.")
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

                st.markdown(f"### ⚔️ **{away_t} @ {home_t}** (Semaine {sel_week})")
                st.dataframe(
                    df_matrix,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Joueurs": st.column_config.Column("Joueurs"),
                        "Ligues (Total)": st.column_config.Column("Ligues (Total)")
                    }
                )

    st.markdown("---")
    
    st.subheader("⚠️ Évolution des Joueurs Inactifs / Injured Reserve (IR)")
    
    inactive_statuses = ["Questionable", "Out", "Doubtful", "IR", "PUP", "SUS"]
    inactive_a = group_a[group_a["status"].isin(inactive_statuses)].copy()
    inactive_b = group_b[group_b["status"].isin(inactive_statuses)].copy()
    
    col_in_1, col_in_2 = st.columns(2)
    with col_in_1:
        st.metric("Inactifs Groupe A (Cibles/Core)", f"{len(inactive_a)}")
    with col_in_2:
        st.metric("Inactifs Groupe B (Vente/Drop)", f"{len(inactive_b)}")

    if not inactive_a.empty or not inactive_b.empty:
        st.markdown("##### 📉 Impact ADP sur les assets affectés")
        combined_inactive = pd.concat([inactive_a, inactive_b])
        
        inactive_rows = []
        for _, p_row in combined_inactive.iterrows():
            current_rank = p_row["search_rank"]
            if p_row["status"] in ["IR", "PUP", "SUS"]:
                trend_val = "🔻 Chute forte (+35 positions)"
            elif p_row["status"] in ["Out", "Doubtful"]:
                trend_val = "🔻 Baisse modérée (+15 positions)"
            else:
                trend_val = "🟧 Stable (-0/5 positions)"
                
            group_tag = "⭐ Groupe A" if p_row["shares"] >= threshold_group_a else "🔄 Groupe B"
            inactive_rows.append({
                "Joueur": f"{p_row['player_name']} ({p_row['position']} - {p_row['team']})",
                "Groupe": group_tag,
                "Statut": p_row["status"],
                "Rank ADP": current_rank if current_rank < 9000 else "N/A",
                "Tendance ADP": trend_val
            })
            
        df_inactive_trend = pd.DataFrame(inactive_rows)
        st.dataframe(
            df_inactive_trend,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Aucun joueur inactif ou blessé détecté dans vos groupes d'exposition actuellement.")

