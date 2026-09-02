import streamlit as st
import pandas as pd
from db import (
    add_excluded_league_db, 
    remove_excluded_league_db, 
    save_all_excluded_leagues_db,
    remove_from_blacklist_db
)

def render_sidebar(all_league_names, league_badge_map, group_b):
    st.sidebar.header("⚙️ Paramètres")
    user_id_input = st.sidebar.text_input("ID Sleeper", value="742374956750540800")
    season_year = st.sidebar.selectbox("Saison", ["2026", "2025"], index=0)
    threshold_group_a = st.sidebar.slider("Seuil Groupe A (Parts min.)", min_value=2, max_value=5, value=3)

    filter_upgrade_pure = st.sidebar.toggle(
        "🔥 Filtre Upgrade Pure",
        value=False,
        help="Masque les opportunités si tes postes titulaires sont déjà sécurisés par des joueurs du Groupe A."
    )

    filter_trade_urgent = st.sidebar.toggle(
        "🚨 Filtre Trade Urgent (No Flex)",
        value=False,
        help="Masque les opportunités si la cible n'apporte pas un vrai gain direct sur tes titulaires stricts (ou si tu as déjà 2+ QBs du Groupe A en Superflex)."
    )

    rank_threshold_b = st.sidebar.number_input(
        "Rank ADP max. asset Groupe B",
        min_value=10, max_value=300, value=100, step=10,
        help="Utilisé lors du recalcul manuel pour masquer les ligues sans bon joueur du Groupe B."
    )

    if "excluded_leagues" not in st.session_state:
        st.session_state["excluded_leagues"] = set()

    with st.sidebar.expander("🏟️ Exclure des Ligues (Radar)", expanded=False):
        available_to_exclude = [l for l in all_league_names if l not in st.session_state["excluded_leagues"]]
        
        selected_to_add = st.selectbox(
            "Taper ou choisir une ligue à masquer :",
            options=["-- Sélectionner une ligue --"] + available_to_exclude,
            key="add_excluded_league_select"
        )
        
        if selected_to_add and selected_to_add != "-- Sélectionner une ligue --":
            st.session_state["excluded_leagues"].add(selected_to_add)
            add_excluded_league_db(selected_to_add)
            st.rerun()

        st.markdown("---")
        
        if st.button("🔄 Recalculer le masquage automatique", help="Analyse les ligues n'ayant aucun joueur Groupe B sous le rang ADP max et met à jour la BDD Turso."):
            valid_b_players = group_b[group_b["search_rank"] <= rank_threshold_b] if group_b is not None else pd.DataFrame()
            leagues_with_valid_b = set()
            if not valid_b_players.empty:
                for _, row in valid_b_players.iterrows():
                    leagues_with_valid_b.update(row["leagues"])
                
            auto_excluded = set(lname for lname in all_league_names if lname not in leagues_with_valid_b)
            st.session_state["excluded_leagues"] = auto_excluded
            save_all_excluded_leagues_db(auto_excluded)
            st.toast("Liste des ligues masquées recalculée et sauvegardée en BDD !", icon="✅")
            st.rerun()

        st.markdown("---")
        st.caption("🚫 **Ligues actuellement masquées (Persistées) :**")
        
        if st.session_state["excluded_leagues"]:
            for exc_league in sorted(list(st.session_state["excluded_leagues"])):
                badge = league_badge_map.get(exc_league, '')
                col_l1, col_l2 = st.columns([4, 1])
                col_l1.markdown(f"• **{exc_league}**\n  <small>`{badge}`</small>", unsafe_allow_html=True)
                if col_l2.button("❌", key=f"unexclude_{exc_league}"):
                    st.session_state["excluded_leagues"].remove(exc_league)
                    remove_excluded_league_db(exc_league)
                    st.rerun()
        else:
            st.write(":gray[Aucune ligue masquée.]")

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

    return user_id_input, season_year, threshold_group_a, filter_upgrade_pure, filter_trade_urgent

