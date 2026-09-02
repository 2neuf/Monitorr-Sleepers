import streamlit as st
import pandas as pd
from sleeper_api import load_sleeper_players, fetch_trending_players

def render_waivers_tab(leagues, draft_completed_leagues, league_rosters_map, user_full_roster_objects, league_size_map):
    st.subheader("📥 Disponibilité des Waivers & Analyse Roster")
    st.caption("Affiche la disponibilité des joueurs (✅ Libre ou ❌ Pris) uniquement dans les ligues dont la draft est terminée.")

    all_players = load_sleeper_players()

    active_waiver_leagues = [
        l["name"] for l in leagues 
        if l["name"] in draft_completed_leagues
    ]

    if not active_waiver_leagues:
        st.warning("Aucune ligue éligible pour les waivers.")
        return

    def get_waiver_status_for_league(p_id, p_pos, l_name):
        taken_set = league_rosters_map.get(l_name, set())
        
        if p_id in taken_set:
            return "❌ Pris"

        my_roster = user_full_roster_objects.get(l_name, [])
        max_roster_size = league_size_map.get(l_name, 25)

        if len(my_roster) < max_roster_size:
            return "✅ Libre (Place dispo)"

        same_pos_players = [p for p in my_roster if p.get("position") == p_pos]

        if same_pos_players:
            worst_player = max(same_pos_players, key=lambda x: x.get("search_rank", 0))
            return f"✅ Libre (Drop : {worst_player['player_name']})"
        else:
            worst_global = max(my_roster, key=lambda x: x.get("search_rank", 0))
            return f"✅ Libre (Drop : {worst_global['player_name']})"

    col_w_head, col_w_btn = st.columns([3, 1])
    with col_w_head:
        st.markdown("### 🔥 Partie 1 : Joueurs Tendance (Trending Adds Sleeper)")
    with col_w_btn:
        if st.button("🔄 Rafraîchir les Trending", key="btn_refresh_trending"):
            fetch_trending_players.clear()
            st.rerun()

    trending_data = fetch_trending_players(type="add", lookback_hours=24, limit=50)

    if trending_data:
        trending_players_map = {}
        available_positions = set()

        for item in trending_data:
            p_id = str(item.get("player_id"))
            p_info = all_players.get(p_id, {})
            p_name = p_info.get("full_name", f"Joueur #{p_id}")
            p_pos = p_info.get("position", "N/A")
            p_team = p_info.get("team", "FA")
            
            label = f"{p_name} ({p_pos} - {p_team})"
            trending_players_map[label] = {
                "id": p_id,
                "pos": p_pos,
                "count": item.get("count", 0)
            }
            if p_pos in ["QB", "RB", "WR", "TE"]:
                available_positions.add(p_pos)

        col_f1, col_f2 = st.columns([1, 2])

        with col_f1:
            selected_positions = st.multiselect(
                "Filtrer par poste :",
                options=sorted(list(available_positions)),
                default=[],
                placeholder="Tous les postes",
                key="waiver_pos_filter"
            )

        filtered_by_pos_map = {
            label: data for label, data in trending_players_map.items()
            if not selected_positions or data["pos"] in selected_positions
        }

        with col_f2:
            selected_trending_labels = st.multiselect(
                "Masquer d'autres joueurs / Masquer ligues si pris :",
                options=list(filtered_by_pos_map.keys()),
                placeholder="Sélectionner un ou plusieurs joueurs...",
                key="waiver_multiselect_trending_only"
            )

        filtered_waiver_leagues = active_waiver_leagues.copy()

        if selected_trending_labels:
            for label in selected_trending_labels:
                p_id = filtered_by_pos_map[label]["id"]
                filtered_waiver_leagues = [
                    l_name for l_name in filtered_waiver_leagues
                    if p_id not in league_rosters_map.get(l_name, set())
                ]

            st.info(
                f"💡 **{len(filtered_waiver_leagues)} / {len(active_waiver_leagues)} ligue(s)** disponible(s) "
                f"où **tous** les joueurs sélectionnés sont encore LIBRES."
            )

            display_targets = {label: filtered_by_pos_map[label] for label in selected_trending_labels}
        else:
            display_targets = filtered_by_pos_map

        trending_rows = []
        for label, p_data in display_targets.items():
            p_id = p_data["id"]
            p_pos = p_data["pos"]
            adds_count = p_data["count"]

            row_dict = {
                "Joueur": label,
                "Adds (24h)": f"🔥 +{adds_count}"
            }

            for l_name in filtered_waiver_leagues:
                row_dict[l_name] = get_waiver_status_for_league(p_id, p_pos, l_name)

            trending_rows.append(row_dict)

        df_trending = pd.DataFrame(trending_rows)

        st.dataframe(
            df_trending,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Joueur": st.column_config.Column("Joueur"),
                "Adds (24h)": st.column_config.Column("Adds (24h)")
            }
        )

    else:
        st.info("Impossible de récupérer les joueurs trending pour le moment.")

    st.markdown("---")

    st.markdown("### 🔍 Partie 2 : Recherche Spécifique de Joueur")

    all_players_options = []
    full_player_id_map = {}

    for p_id, p_info in all_players.items():
        full_name = p_info.get("full_name")
        pos = p_info.get("position")
        team = p_info.get("team")
        if full_name and pos in ["QB", "RB", "WR", "TE"]:
            label = f"{full_name} ({pos} - {team or 'FA'})"
            all_players_options.append(label)
            full_player_id_map[label] = (p_id, pos)

    all_players_options.sort()

    selected_search_label = st.selectbox(
        "Rechercher un joueur spécifique à ajouter :",
        options=["-- Taper pour chercher un joueur --"] + all_players_options,
        key="waiver_search_selectbox"
    )

    if selected_search_label and selected_search_label != "-- Taper pour chercher un joueur --":
        searched_p_id, searched_p_pos = full_player_id_map.get(selected_search_label)
        
        search_rows = []
        row_dict = {"Joueur": selected_search_label}

        for l_name in active_waiver_leagues:
            row_dict[l_name] = get_waiver_status_for_league(searched_p_id, searched_p_pos, l_name)

        search_rows.append(row_dict)
        df_search = pd.DataFrame(search_rows)
        st.dataframe(
            df_search, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Joueur": st.column_config.Column("Joueur")
            }
        )

