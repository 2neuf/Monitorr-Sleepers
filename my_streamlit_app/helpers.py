import math
import pandas as pd
import streamlit as st
from sleeper_api import (
    load_sleeper_players, 
    fetch_user_leagues, 
    fetch_league_rosters, 
    fetch_league_users, 
    fetch_league_draft_info, 
    fetch_league_traded_picks
)
from datetime import datetime

def get_current_nfl_week() -> int:
    """Calcule automatiquement la semaine NFL courante basée sur la date actuelle."""
    today = datetime.now()
    # Début estimé de la saison régulière (premier jeudi de septembre)
    # Pour 2026, la semaine 1 démarre début septembre.
    # Ajuste l'année/mois de référence si besoin :
    season_start = datetime(today.year, 9, 3) 
    
    if today < season_start:
        return 1
    
    delta_days = (today - season_start).days
    current_week = (delta_days // 7) + 1
    
    # Borne entre 1 et 18
    return max(1, min(current_week, 18))

def get_league_format_badge(roster_positions, league_settings):
    """Génère le badge émoji selon le format (ex: ⚡🏰 SF Dynasty)."""
    roster_pos = roster_positions or []
    is_sf = "SUPER_FLEX" in roster_pos or roster_pos.count("QB") >= 2
    is_dynasty = league_settings.get("type") != 0  # 0 = Redraft sur Sleeper
    
    qb_icon = "⚡" if is_sf else "🎯"
    type_icon = "🏰" if is_dynasty else "🔄"
    
    qb_label = "SF" if is_sf else "1QB"
    type_label = "Dynasty" if is_dynasty else "Redraft"
    
    return f"{qb_icon}{type_icon} {qb_label} {type_label}"


def get_adjusted_player_rank(p_info, is_superflex=True, is_dynasty=True):
    """Ajuste l'ADP Redraft 1QB brut de Sleeper pour refléter la valeur SF/Dynasty."""
    raw_rank = p_info.get("search_rank") or 9999
    pos = p_info.get("position")
    
    age = p_info.get("age")
    if age is None:
        age = 25

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
        estimated_pick_pos = slot
        tier_label = f"Pick {season} #{rd}.{slot:02d}"
    else:
        if orig_id == my_roster_id:
            estimated_pick_pos = max(1, int(total_teams * 0.75))
            tier_label = f"Pick {season} Mid/Late {rd}st" if rd == 1 else f"Pick {season} Mid/Late {rd}nd"
        else:
            estimated_pick_pos = max(1, int(total_teams * 0.35))
            tier_label = f"Pick {season} Early/Mid {rd}st" if rd == 1 else f"Pick {season} Early/Mid {rd}nd"

    if rd == 1:
        base_rank = 15
    elif rd == 2:
        base_rank = 45
    elif rd == 3:
        base_rank = 75
    else:
        base_rank = 110

    rank_val = base_rank + (estimated_pick_pos - 1) * 2
    if not is_current:
        rank_val += 12

    label = f"🎟️ {tier_label} (@{orig_pseudo}) [Rank #{rank_val}]"
    pick_name = f"Pick {season} Rd {rd} (@{orig_pseudo})"
    return rank_val, label, pick_name


def parse_roster_requirements(roster_positions):
    """Compte le nombre de starters requis par poste dans la ligue."""
    counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "SUPER_FLEX": 0}
    if not roster_positions:
        return {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "SUPER_FLEX": 0}
        
    for pos in roster_positions:
        if pos in counts:
            counts[pos] += 1
        elif pos in ["REC_FLEX", "WRRB_FLEX"]:
            counts["FLEX"] += 1
            
    return counts


def is_pure_upgrade(my_group_a_roster, target_player, reqs):
    t_pos = target_player.get("target_pos")
    if t_pos not in ["QB", "RB", "WR", "TE"]:
        return True

    t_rank = target_player.get("target_rank", 9999)
    my_by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in my_group_a_roster:
        pos = p.get("position")
        if pos in my_by_pos:
            my_by_pos[pos].append(p.get("search_rank", 9999))
            
    for pos in my_by_pos:
        my_by_pos[pos].sort()

    needed_strict = reqs.get(t_pos, 0)
    current_strict = my_by_pos[t_pos][:needed_strict]
    
    if len(current_strict) < needed_strict:
        return True
    if current_strict and t_rank < (current_strict[-1] - 15):
        return True

    flex_candidates = []
    for pos in ["RB", "WR", "TE"]:
        start_idx = reqs.get(pos, 0)
        flex_candidates.extend(my_by_pos[pos][start_idx:])
    flex_candidates.sort()
    
    needed_flex = reqs.get("FLEX", 0)
    current_flex = flex_candidates[:needed_flex]
    
    if t_pos in ["RB", "WR", "TE"]:
        if len(current_flex) < needed_flex:
            return True
        if current_flex and t_rank < (current_flex[-1] - 15):
            return True

    sf_candidates = []
    sf_candidates.extend(my_by_pos["QB"][reqs.get("QB", 0):])
    for pos in ["RB", "WR", "TE"]:
        start_idx = reqs.get(pos, 0) + (1 if pos in ["RB", "WR", "TE"] and len(my_by_pos[pos]) > reqs.get(pos, 0) else 0)
        sf_candidates.extend(my_by_pos[pos][start_idx:])
    sf_candidates.sort()
    
    needed_sf = reqs.get("SUPER_FLEX", 0)
    current_sf = sf_candidates[:needed_sf]
    
    if len(current_sf) < needed_sf:
        return True
    if current_sf and t_rank < (current_sf[-1] - 15):
        return True

    return False


def passes_trade_urgent_no_flex(target_player, user_roster, reqs, group_a_ids_set=None):
    pos = target_player.get("target_pos")
    if pos not in ["QB", "RB", "WR", "TE"]:
        return True

    is_sf = reqs.get("SUPER_FLEX", 0) > 0 or reqs.get("QB", 0) >= 2

    if pos == "QB" and is_sf and group_a_ids_set:
        group_a_qbs_count = sum(
            1 for p in user_roster 
            if p.get("position") == "QB" and p.get("player_id") in group_a_ids_set
        )
        if group_a_qbs_count >= 2:
            return False

    roster_pos = [p for p in user_roster if p.get("position") == pos]
    strict_slots_count = reqs.get(pos, 1)
    if strict_slots_count == 0:
        strict_slots_count = 1
        
    if len(roster_pos) < strict_slots_count:
        return True

    sorted_roster = sorted(roster_pos, key=lambda x: x.get("search_rank", 9999))
    cutoff_starter = sorted_roster[strict_slots_count - 1]
    cutoff_rank = cutoff_starter.get("search_rank", 9999)
    target_rank = target_player.get("target_rank", 9999)

    min_rank_diff = 15 if not (pos == "QB" and not is_sf) else 25
    return target_rank <= (cutoff_rank - min_rank_diff)


@st.cache_data(ttl=600)
def compute_all_data_and_opportunities(
    user_id, year, threshold_a, accepted_trades_tuple=()
):
    all_players = load_sleeper_players()
    leagues = fetch_user_leagues(user_id, year)

    if not leagues:
        return None, None, None, [], [], {}, {}, {}, {}, {}

    league_name_to_id = {l["name"]: l["league_id"] for l in leagues}
    league_size_map = {league["name"]: len(league.get("roster_positions") or []) for league in leagues}
    league_reqs_map = {league["name"]: parse_roster_requirements(league.get("roster_positions")) for league in leagues}

    name_to_player_id = {p_info.get("full_name"): p_id for p_id, p_info in all_players.items() if p_info.get("full_name")}

    user_rosters = []
    user_roster_ids = {}
    league_rosters_map = {} 
    user_full_roster_objects = {}
    draft_completed_leagues = set()

    for league in leagues:
        l_id = league["league_id"]
        l_name = league["name"]
        rosters = fetch_league_rosters(l_id)
        roster_to_slot, completed_seasons, is_upcoming_draft_done = fetch_league_draft_info(l_id)
        
        league_status = league.get("status")
        if league_status in ["in_season", "active"] or is_upcoming_draft_done:
            draft_completed_leagues.add(l_name)
        
        taken_in_league = set()
        user_full_roster_objects[l_name] = []

        for roster in rosters:
            r_players = roster.get("players") or []
            for p_id in r_players:
                taken_in_league.add(str(p_id))
                
            if roster.get("owner_id") == user_id:
                user_roster_ids[l_id] = roster.get("roster_id")
                for p_id in r_players:
                    p_info = all_players.get(str(p_id), {})
                    p_obj = {
                        "player_id": str(p_id),
                        "player_name": p_info.get("full_name", f"Joueur #{p_id}"),
                        "position": p_info.get("position", "N/A"),
                        "search_rank": p_info.get("search_rank") or 9999,
                        "status": p_info.get("status", "Active")
                    }
                    user_rosters.append({
                        "player_id": str(p_id),
                        "league_id": l_id,
                        "league_name": l_name,
                    })
                    user_full_roster_objects[l_name].append(p_obj)

        league_rosters_map[l_name] = taken_in_league

    traded_away_picks = set()

    for trade_league, target_id, target_name, offered_names in accepted_trades_tuple:
        t_league_id = league_name_to_id.get(trade_league)
        if not t_league_id:
            continue

        acq_id = str(target_id) if target_id else name_to_player_id.get(target_name)
        if acq_id:
            user_rosters.append({
                "player_id": str(acq_id),
                "league_id": t_league_id,
                "league_name": trade_league,
            })

        for off_item in offered_names:
            if off_item in name_to_player_id:
                off_p_id = str(name_to_player_id[off_item])
                user_rosters = [
                    r for r in user_rosters
                    if not (r["league_name"] == trade_league and r["player_id"] == off_p_id)
                ]
            else:
                traded_away_picks.add((trade_league, off_item))

    if not user_rosters:
        return None, None, None, [], [], {}, {}, {}, {}, set()

    df_rosters = pd.DataFrame(user_rosters)

    def _get_info(p_id):
        p_info = all_players.get(str(p_id), {})
        return (
            p_info.get("full_name", f"Joueur inconnu ({p_id})"),
            p_info.get("position", "N/A"),
            p_info.get("team", "N/A"),
            p_info.get("search_rank") or 9999,
            p_info.get("status", "Active")
        )

    df_rosters[["player_name", "position", "team", "search_rank", "status"]] = (
        df_rosters["player_id"].apply(lambda x: pd.Series(_get_info(x)))
    )

    exposure = (
        df_rosters.groupby(["player_id", "player_name", "position", "team", "search_rank", "status"])
        .agg(shares=("league_id", "count"), leagues=("league_name", lambda x: list(x)))
        .reset_index()
    )

    group_a = exposure[exposure["shares"] >= threshold_a].sort_values(by="search_rank", ascending=True)
    group_b = exposure[exposure["shares"] < threshold_a].sort_values(by="search_rank", ascending=True)

    group_a_ids = set(group_a["player_id"])
    group_b_ids = set(group_b["player_id"])

    group_a_roster_by_league = {}
    full_roster_by_league = {}
    for _, r_row in df_rosters.iterrows():
        l_name = r_row["league_name"]
        if l_name not in full_roster_by_league:
            full_roster_by_league[l_name] = []
            group_a_roster_by_league[l_name] = []
            
        full_roster_by_league[l_name].append({
            "player_id": r_row["player_id"],
            "position": r_row["position"],
            "search_rank": r_row["search_rank"]
        })
        if r_row["player_id"] in group_a_ids:
            group_a_roster_by_league[l_name].append({
                "player_id": r_row["player_id"],
                "position": r_row["position"],
                "search_rank": r_row["search_rank"]
            })

    target_opportunities = []

    for league in leagues:
        l_id = league["league_id"]
        l_name = league["name"]
        my_roster_id = user_roster_ids.get(l_id)

        roster_pos_list = league.get("roster_positions") or []
        is_sf = "SUPER_FLEX" in roster_pos_list or roster_pos_list.count("QB") >= 2
        is_dynasty = league.get("settings", {}).get("type") != 0

        my_b_in_league = df_rosters[(df_rosters["league_id"] == l_id) & (df_rosters["player_id"].isin(group_b_ids))].copy()

        league_users = fetch_league_users(l_id)
        rosters = fetch_league_rosters(l_id)
        total_teams = len(rosters) or league.get("total_rosters", 12)

        roster_id_to_pseudo = {
            r.get("roster_id"): league_users.get(r.get("owner_id"), f"Équipe #{r.get('roster_id')}")
            for r in rosters
        }

        roster_to_slot, completed_seasons, _ = fetch_league_draft_info(l_id)

        draft_rounds = league.get("settings", {}).get("draft_rounds", 4)
        future_years = [str(int(year) + i) for i in range(0, 3)]
        valid_years = [yr for yr in future_years if yr not in completed_seasons]

        owned_picks = set()
        if my_roster_id:
            for yr in valid_years:
                for rd in range(1, draft_rounds + 1):
                    owned_picks.add((yr, rd, my_roster_id))

            traded_picks = fetch_league_traded_picks(l_id)
            for tp in traded_picks:
                tp_season = str(tp.get("season"))
                if tp_season in completed_seasons:
                    continue

                tp_round = tp.get("round")
                tp_orig = tp.get("roster_id")
                tp_owner = tp.get("owner_id")

                if tp_orig == my_roster_id and tp_owner != my_roster_id:
                    owned_picks.discard((tp_season, tp_round, tp_orig))
                elif tp_owner == my_roster_id:
                    owned_picks.add((tp_season, tp_round, tp_orig))

        b_options_list = []

        for _, row in my_b_in_league.iterrows():
            p_info = all_players.get(str(row["player_id"]), {})
            adj_rank = get_adjusted_player_rank(p_info, is_superflex=is_sf, is_dynasty=is_dynasty)
            label = f"🏃 {row['player_name']} ({row['position']} - {row['team']}) [Rank #{adj_rank}]"
            b_options_list.append((adj_rank, label, row["player_name"]))

        for season, rd, orig_id in owned_picks:
            orig_pseudo = roster_id_to_pseudo.get(orig_id, f"#{orig_id}")
            rank_val, label, pick_name = calculate_pick_rank_and_label(
                season, rd, orig_id, my_roster_id, roster_to_slot, total_teams, orig_pseudo, year
            )
            if (l_name, pick_name) not in traded_away_picks:
                b_options_list.append((rank_val, label, pick_name))

        b_options_list.sort(key=lambda x: x[0])
        final_b_options = [opt[1] for opt in b_options_list]
        final_b_names_map = {opt[1]: opt[2] for opt in b_options_list}

        reqs = league_reqs_map.get(l_name, {})
        my_g_a = group_a_roster_by_league.get(l_name, [])
        my_full = full_roster_by_league.get(l_name, [])

        for r in rosters:
            if r.get("owner_id") != user_id:
                r_players = set(r.get("players") or [])
                targets_held = r_players.intersection(group_a_ids)

                if targets_held:
                    owner_pseudo = league_users.get(r.get("owner_id"), "Propriétaire Inconnu")

                    for target_id in targets_held:
                        p_info = all_players.get(str(target_id), {})
                        t_name = p_info.get("full_name", f"Joueur inconnu ({target_id})")
                        t_pos = p_info.get("position", "N/A")
                        t_team = p_info.get("team", "N/A")
                        t_rank = get_adjusted_player_rank(p_info, is_superflex=is_sf, is_dynasty=is_dynasty)

                        target_obj = {
                            "target_id": target_id,
                            "target_name": t_name,
                            "target_pos": t_pos,
                            "target_team": t_team,
                            "target_rank": t_rank,
                            "league_name": l_name,
                            "owner_pseudo": owner_pseudo,
                            "b_options": final_b_options,
                            "b_names_map": final_b_names_map,
                            "is_pure_upgrade": is_pure_upgrade(my_g_a, {"target_pos": t_pos, "target_rank": t_rank}, reqs),
                            "is_trade_urgent": passes_trade_urgent_no_flex(
                                {"target_pos": t_pos, "target_rank": t_rank}, 
                                my_full, 
                                reqs, 
                                group_a_ids_set=group_a_ids
                            )
                        }

                        target_opportunities.append(target_obj)

    target_opportunities.sort(key=lambda x: x["target_rank"])
    return (
        df_rosters,
        group_a,
        group_b,
        target_opportunities,
        leagues,
        league_size_map,
        league_reqs_map,
        league_rosters_map,
        user_full_roster_objects,
        draft_completed_leagues,
    )

