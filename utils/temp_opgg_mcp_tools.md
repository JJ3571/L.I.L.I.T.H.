lol_list_summoner_matches
Returns recent match history with per-game stats for the target summoner only (excludes enemy stats). MUST call for match history, performance analysis, or improvement tips. DO NOT call for profile/rank queries. Use lol_get_summoner_game_detail for full game details with all players.
• game_name (string) - REQUIRED
└ Riot ID game name before the "#" (e.g., "Faker" from "Faker#KR1")
• tag_line (string) - REQUIRED
└ Riot ID tag line following the "#" (e.g., "KR1" from "Faker#KR1")
• region (string) - REQUIRED
└ Server region code (e.g., KR, NA, EUW)
• lang (string) - REQUIRED
└ Locale code (e.g., en_US, ko_KR, ja_JP)
• limit (integer) - optional
└ Maximum number of matches to return.
• desired_output_fields (array) - REQUIRED
└ Select ONLY from fields below. This is a CLOSED SET. Do NOT invent new field names.

Available fields:
data.game_history[].average_tier_info.{border_image_url,division,tier}
data.game_history[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}
data.game_history[].participants[].stats.op_score_timeline[].{score,second}
data.game_history[].participants[].stats.op_score_timeline_analysis.{last,left,right}
data.game_history[].participants[].stats.{assist,champion_level,death,gold_earned,kill,largest_critical_strike,largest_killing_spree,largest_multi_kill,minion_kill,neutral_minion_kill,neutral_minion_kill_enemy_jungle,neutral_minion_kill_team_jungle,op_score,op_score_rank,result,time_ccing_others,total_damage_dealt_to_champions,total_damage_taken,total_heal,vision_wards_bought_in_game,ward_place}
data.game_history[].participants[].summoner.player.{esports_url,nickname,real_name}
data.game_history[].participants[].summoner.{game_name,puuid,tagline}
data.game_history[].participants[].{champion_id,champion_name,items[],items_names[],position,spells[],team_key}
data.game_history[].teams[].game_stat.{atakhan_kill,baron_kill,champion_first,champion_kill,dragon_kill,gold_earned,horde_kill,inhibitor_kill,is_win,rift_herald_kill,tower_kill}
data.game_history[].teams[].{banned_champions[],banned_champions_names[],key}
data.game_history[].{created_at,game_length_second,game_map,game_type,id}

Field descriptions:
game_history.*.game_type: Game queue type (SOLORANKED, FLEXRANKED, NORMAL, ARAM, etc.)
game_history.*.average_tier_info: Average rank tier of players in the match
game_history..participants..team_key: Team side (RED=bottom-right, BLUE=top-left)

ol_get_summoner_game_detail
Returns full match detail (teams, participants, builds, bans) for a specific game id whenever the user drills into a single match.
• region (string) - REQUIRED
└ Server region code (e.g., KR, NA, EUW)
• lang (string) - REQUIRED
└ Locale code (e.g., en_US, ko_KR, ja_JP)
• game_id (string) - REQUIRED
└ Unique identifier for the target match.
• created_at (string) - REQUIRED
└ Match creation timestamp (ISO-8601).
• desired_output_fields (array) - REQUIRED
└ Select ONLY from fields below. This is a CLOSED SET. Do NOT invent new field names.

Available fields:
data.game_detail.average_tier_info.{border_image_url,division,tier}
data.game_detail.participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}
data.game_detail.participants[].stats.op_score_timeline[].{score,second}
data.game_detail.participants[].stats.op_score_timeline_analysis.{last,left,right}
data.game_detail.participants[].stats.{assist,champion_level,death,gold_earned,kill,largest_critical_strike,largest_killing_spree,largest_multi_kill,minion_kill,neutral_minion_kill,neutral_minion_kill_enemy_jungle,neutral_minion_kill_team_jungle,op_score,op_score_rank,result,time_ccing_others,total_damage_dealt_to_champions,total_damage_taken,total_heal,vision_wards_bought_in_game,ward_place}
data.game_detail.participants[].summoner.player.{esports_url,nickname,real_name}
data.game_detail.participants[].summoner.{game_name,puuid,tagline}
data.game_detail.participants[].{champion_id,champion_name,items[],items_names[],position,spells[],team_key}
data.game_detail.teams[].game_stat.{atakhan_kill,baron_kill,champion_first,champion_kill,dragon_kill,gold_earned,horde_kill,inhibitor_kill,is_win,rift_herald_kill,tower_kill}
data.game_detail.teams[].{banned_champions[],banned_champions_names[],key}
data.game_detail.{created_at,game_length_second,game_map,game_type,id}

Field descriptions:
game_detail.game_type: Game queue type (SOLORANKED, FLEXRANKED, NORMAL, ARAM, etc.)
game_detail.average_tier_info: Average rank tier of players in the match
game_detail.participants.*.team_key: Team side (RED=bottom-right, BLUE=top-left)
game_detail.participants.*.stats.op_score: OP.GG performance score (0-10 scale)
game_detail.participants.*.stats.minion_kill: Lane minions killed (CS from lane)
game_detail.participants.*.stats.neutral_minion_kill: Jungle monsters killed (CS from jungle)

lol_get_lane_matchup_guide
Provides lane matchup guidance for your champion versus a named opponent, including position-specific tips, runes, and item timings.
• lang (string) - REQUIRED
└ Locale code (e.g., en_US, ko_KR, ja_JP)
• position (string) - REQUIRED
└ Lane position (top, mid, jungle, adc, support)
• my_champion (string) - REQUIRED
└ Champion name in UPPER_SNAKE_CASE (e.g., AHRI, LEE_SIN)
• opponent_champion (string) - REQUIRED
└ Champion name in UPPER_SNAKE_CASE (e.g., AHRI, LEE_SIN)
lol_esports_list_schedules
Returns upcoming LoL esports schedules with teams, leagues, and match times in ISO 8601 UTC format. Always convert to user's timezone before presenting.
No parameters required

lol_esports_list_team_standings
Returns the latest team standings for the requested LoL league.
• short_name (string) - REQUIRED (Options: lck, lpl, lec, lcs, ljl, vcs, cblol, lcl, lla, tcl, pcs, lco, lta south, lta north, lcp, first stand, fst, al, msi, worlds)