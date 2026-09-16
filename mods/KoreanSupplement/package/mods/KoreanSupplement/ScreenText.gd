extends RefCounted
const Display = preload("res://KoreanSupplement/DisplayText.gd")
const Names = preload("res://KoreanSupplement/PersonalNames.gd")
const TEAMS := {
	"The Power Ballad": "파워 발라드",
	"Ironvale Wardens": "아이언베일 수호대",
	"Order of Innervision": "이너비전 기사단",
	"Fury United": "분노 연합",
	"Aconcagua": "아콩카과"
}
const HEADERS := {
	"NAME": "이름", "TEAM": "팀", "CLASS": "직업", "PRICE": "가격",
	"CUSTOM": "직접 정렬", "LVL": "레벨", "HP": "체력", "ATK": "공격력",
	"PWR": "전투력", "DEF": "방어력", "SPD": "속도", "K/D": "처치/사망",
	"VALUE": "가치", "RARITY": "등급", "TYPE": "종류"
}

static func _save() -> Variant:
	var tree = Engine.get_main_loop() as SceneTree
	var service = tree.root.get_node_or_null("CampaignService") if tree != null else null
	return service.get("current_save") if service != null else null

static func _replace_names(text: String, candidates: Dictionary) -> String:
	# Replace only complete known names, never a name embedded inside an ID.
	var sources := candidates.keys()
	sources.sort_custom(func(a, b): return str(a).length() > str(b).length())
	var result := ""
	var cursor := 0
	while cursor < text.length():
		var found := false
		for source_value in sources:
			var source := str(source_value)
			if source.is_empty() or text.substr(cursor, source.length()).nocasecmp_to(source) != 0:
				continue
			var end := cursor + source.length()
			if (cursor > 0 and Display._identifier_char(text.unicode_at(cursor - 1))) or (end < text.length() and Display._identifier_char(text.unicode_at(end))):
				continue
			result += text.substr(cursor, source.length()) if source.nocasecmp_to(str(candidates[source])) == 0 else str(candidates[source])
			cursor = end
			found = true
			break
		if not found:
			result += text[cursor]
			cursor += 1
	return result

static func teams(value: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	var candidates := TEAMS.duplicate()
	var save = _save()
	if save != null:
		for raw in candidates.keys():
			if str(save.player_team_name).nocasecmp_to(raw) == 0:
				candidates.erase(raw)
		if not str(save.player_team_name).is_empty():
			candidates[str(save.player_team_name)] = str(save.player_team_name)
	return _replace_names(original, candidates)

static func header(value: Variant) -> String:
	var original := str(value)
	return str(HEADERS.get(original.to_upper(), original)) if Names._is_korean() else original

static func roster_counts(value: String) -> String:
	return "주전 %d/%d - 선수단 %d/%d - 훈련 %d/%d - 아카데미 %d/%d" if Names._is_korean() else value

static func calendar(value: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	var regex := RegEx.new()
	regex.compile("(?i)^(\\d+)v(\\d+) CUP(?: (NEXT|QUARTERFINALS?|SEMIFINALS?|FINAL|ROUND OF 16))?$")
	var match_result := regex.search(original.strip_edges())
	if match_result != null:
		var stage := match_result.get_string(3).to_upper()
		var stages := {"": "", "NEXT": "개막 예정", "QUARTERFINAL": "8강", "QUARTERFINALS": "8강", "SEMIFINAL": "4강", "SEMIFINALS": "4강", "FINAL": "결승", "ROUND OF 16": "16강"}
		return ("%s대%s 컵 " % [match_result.get_string(1), match_result.get_string(2)] + str(stages[stage])).strip_edges()
	return teams(Display.term(original))

static func _add_fighter(candidates: Dictionary, fighter: Variant, upper_text: String) -> void:
	if fighter == null:
		return
	var raw := str(fighter.display_name)
	if raw.length() >= 3 and upper_text.contains(raw.to_upper()):
		candidates[raw] = Names.name_of(fighter)

static func news(value: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	var save = _save()
	var candidates := {}
	var upper := original.to_upper()
	if save != null:
		for fighter in save.owned_mercenaries:
			_add_fighter(candidates, fighter, upper)
		for team in save.league_standings:
			if team == null:
				continue
			for fighter in team.roster:
				_add_fighter(candidates, fighter, upper)
			for row in team.compact_roster:
				var raw := str(row.get("display_name", ""))
				if raw.length() >= 3 and upper.contains(raw.to_upper()):
					candidates[raw] = Display.person(raw)
	var result := teams(_replace_names(original, candidates))
	if result.to_upper().begins_with("PLAYER OF THE WEEK: "):
		result = "이번 주의 선수: " + result.substr("PLAYER OF THE WEEK: ".length())
	return result
