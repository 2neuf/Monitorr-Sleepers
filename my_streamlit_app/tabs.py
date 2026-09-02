
import streamlit as st
import pandas as pd
from datetime import datetime
from config import get_nfl_schedule_2026
from db import (
    add_to_blacklist_db,
    update_trade_status_in_db,
    add_trade_to_db,
    delete_all_trades_db
)
from helpers import get_asset_value
from sleeper_api import load_sleeper_players, fetch_trending_players


def render_group_a_tab(group_a, threshold_group_a, league_badge_map, pending_target_pairs, pending_offered_pairs):
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
                badge_str = f" `{league_badge_map.get(l_name, '')}`" if l_name in league_badge_map else ""
                st.markdown(f"• {l_name}{badge_str}{tag}")


def render_group_b_tab(group_b, threshold_group_a, league_badge_map, pending_target_pairs, pending_offered_pairs):
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
                badge_str = f" `{league_badge_map.get(l_name, '')}`" if l_name in league_badge_map else ""
                st.markdown(f"• {l_name}{badge_str}{tag}")


def save_trade_callback(select_key, trade_entry):
    st.session_state["trade_history"].append(trade_entry)
    add_trade_to_db(trade_entry)
    st.session_state[select_key] = []
    st.toast("Proposition enregistrée avec succès !", icon="📌")


def render_radar_tab(
    leagues, draft_completed_leagues, excluded_leagues_input, league_badge_map,
    pending_trades, target_opportunities, pending_target_pairs,
    filter_upgrade_pure, filter_trade_urgent
):
    post_draft_leagues = [
        l["name"] for l in leagues 
        if l["name"] in draft_completed_leagues and l["name"] not in excluded_leagues_input
    ]

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        selected_league = st.selectbox(
            "Filtrer par ligue (Post-Draft)", 
            ["Toutes"] + post_draft_leagues, 
            format_func=lambda name: f"{name} ({league_badge_map.get(name, '')})" if name != "Toutes" else "Toutes",
            key="trade_league_filter"
        )
    with col_f2:
        selected_pos = st.selectbox("Filtrer par poste ciblé", ["Tous", "QB", "RB", "WR", "TE"], key="trade_pos_filter")

    st.markdown("---")

    filtered_pending_trades = [
        t for t in pending_trades 
        if t["league"] in draft_completed_leagues and (selected_league == "Toutes" or t["league"] == selected_league)
    ]

    if filtered_pending_trades:
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

            for p_idx, p_trade in enumerate(filtered_pending_trades):
                badge_str = f" `[{league_badge_map.get(p_trade['league'], '')}]`" if p_trade['league'] in league_badge_map else ""
                with st.expander(f"⏳ **{p_trade['target_full']}** | Ligue : *{p_trade['league']}*{badge_str} | Owner : **@{p_trade['owner']}**", expanded=True):
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
        radar_opps = []
        for o in target_opportunities:
            l_name = o["league_name"]
            
            if l_name not in draft_completed_leagues:
                continue
            if l_name in excluded_leagues_input:
                continue
            if o["owner_pseudo"] in st.session_state["blacklisted_owners"]:
                continue
            if (o["target_name"], l_name, o["owner_pseudo"]) in st.session_state["blacklisted_targets"]:
                continue
            if (o["target_name"], l_name) in pending_target_pairs:
                continue

            if filter_upgrade_pure and not o.get("is_pure_upgrade", True):
                continue
            if filter_trade_urgent and not o.get("is_trade_urgent", True):
                continue

            radar_opps.append(o)

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
                    league_options = [
                        f"{o['league_name']} | @{o['owner_pseudo']} ({league_badge_map.get(o['league_name'], '')})" 
                        for o in opps_list
                    ]
                    selected_league_label = st.selectbox(
                        "Choisir la ligue :",
                        options=league_options,
                        key=f"select_league_for_player_{target_name}_{player_idx}"
                    )
                    selected_idx = league_options.index(selected_league_label)
                else:
                    selected_idx = 0
                    l_badge = league_badge_map.get(first_opp['league_name'], '')
                    st.caption(f"🏟️ Ligue : **{first_opp['league_name']}** (`{l_badge}`) | Owner : **@{first_opp['owner_pseudo']}**")

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


def render_waivers_tab(leagues, excluded_leagues_input, draft_completed_leagues, league_rosters_map, user_full_roster_objects, league_size_map):
    st.subheader("📥 Disponibilité des Waivers & Analyse Roster")
    st.caption("Affiche la disponibilité des joueurs (✅ Libre ou ❌ Pris) uniquement dans les ligues dont la draft est terminée.")

    all_players = load_sleeper_players()

    active_waiver_leagues = [
        l["name"] for l in leagues 
        if l["name"] not in excluded_leagues_input and l["name"] in draft_completed_leagues
    ]

    if not active_waiver_leagues:
        st.warning("Aucune ligue éligible pour les waivers.")
    else:

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
                    options=sorted(list(available_posi