extends RefCounted
## Display-only adapters. Never rewrite resource IDs, stored names or inventory.
const Names = preload("res://KoreanSupplement/PersonalNames.gd")
static var _terms: Dictionary = {}
static var _terms_ready := false
static var _folded_names: Dictionary = {}
static var _ability_terms: Dictionary = {}
# These English skill names have inconsistent Korean synonyms in the game's
# own tables. Use reviewed Korean names only on skill-specific display routes.
const ABILITY_ALIASES := {
	"shared grace": "나눔의 은총", "combat roll": "전투 구르기",
	"shared aegis": "나눔의 방패", "iron resolve": "강철의 결의",
	"blood pact": "피의 계약", "last rites": "최후의 의식",
	"dread howl": "공포의 포효", "skybreaker": "하늘 가르기",
	"deep cut": "깊은 상처", "bloodrush": "핏빛 돌진",
	"falling star": "낙하성", "debt collector": "빚 수금자",
	"slingshot": "새총", "absolute zero": "절대영도",
	"open invitation": "열린 초대"
}

static func person(value: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	# A snapshot may only carry a string. Respect an explicitly renamed owned
	# fighter even if their chosen name coincides with a generated English name.
	var tree = Engine.get_main_loop() as SceneTree
	var campaign = tree.root.get_node_or_null("CampaignService") if tree != null else null
	var save = campaign.get("current_save") if campaign != null else null
	if save != null:
		for fighter in save.owned_mercenaries:
			if fighter != null and str(fighter.display_name) == original and fighter.has_meta(Names.CUSTOM_META) and bool(fighter.get_meta(Names.CUSTOM_META)):
				return original
	var clean := original.strip_edges()
	var translated := Names.text(clean)
	if translated != clean:
		return translated
	# Compact/history surfaces may have stored an upper-case presentation.
	Names._load_data()
	if _folded_names.is_empty():
		for group in ["names", "fixed"]:
			for source in Names._data.get(group, {}):
				if not _folded_names.has(str(source).to_lower()):
					_folded_names[str(source).to_lower()] = Names._data[group][source]
	if _folded_names.has(clean.to_lower()):
		return str(_folded_names[clean.to_lower()])
	for title in Names._data.get("titles", {}):
		var ending := " " + str(title)
		if clean.to_lower().ends_with(ending.to_lower()):
			var first := clean.left(clean.length() - ending.length())
			if _folded_names.has(first.to_lower()):
				return str(Names._data.titles[title]) + " " + str(_folded_names[first.to_lower()])
	return original

static func person_for_id(value: Variant, fighter_id: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	var tree = Engine.get_main_loop() as SceneTree
	var campaign = tree.root.get_node_or_null("CampaignService") if tree != null else null
	var save = campaign.get("current_save") if campaign != null else null
	var fighter = save.get_mercenary_by_id(str(fighter_id)) if save != null else null
	if fighter != null and original == str(fighter.display_name):
		return Names.name_of(fighter)
	return person(original)

static func snapshot(row: Dictionary, key: String, fallback: Variant = "") -> String:
	var value = row.get(key, fallback)
	var id_keys := ["instance_id", "merc_instance_id", "fighter_id", "mercenary_id"]
	if key.ends_with("_display_name"):
		id_keys.push_front(key.replace("_display_name", "_instance_id"))
	for id_key in id_keys:
		if row.has(id_key):
			return person_for_id(value, row[id_key])
	return person(value)

static func people(values: Variant) -> Array[String]:
	var result: Array[String] = []
	for value in values:
		result.append(person(value))
	return result

static func notice(value: Variant, row: Dictionary) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	# Only use names identified by this notification's fields/IDs. Do not scan
	# arbitrary prose for every dictionary name (Rose, Hunter, etc. are words too).
	var candidates := {}
	for key in ["merc_display_name", "offered_merc_display_name", "target_merc_display_name", "fighter_name"]:
		if row.has(key):
			candidates[str(row[key])] = snapshot(row, key)
	var tree = Engine.get_main_loop() as SceneTree
	var campaign = tree.root.get_node_or_null("CampaignService") if tree != null else null
	var save = campaign.get("current_save") if campaign != null else null
	if save != null:
		for key in ["merc_instance_id", "offered_merc_instance_id", "target_merc_instance_id", "fighter_id"]:
			var fighter = save.get_mercenary_by_id(str(row.get(key, "")))
			if fighter != null:
				candidates[str(fighter.display_name)] = Names.name_of(fighter)
	var sources: Array = candidates.keys()
	sources.sort_custom(func(a, b): return str(a).length() > str(b).length())
	var result := ""
	var cursor := 0
	while cursor < original.length():
		var found := false
		for source_value in sources:
			var source := str(source_value)
			if source.is_empty() or source == candidates[source] or not original.substr(cursor).begins_with(source):
				continue
			var end := cursor + source.length()
			if (cursor > 0 and _identifier_char(original.unicode_at(cursor - 1))) or (end < original.length() and _identifier_char(original.unicode_at(end))):
				continue
			result += str(candidates[source])
			cursor = end
			found = true
			break
		if not found:
			result += original[cursor]
			cursor += 1
	return result

static func _identifier_char(code: int) -> bool:
	return (code >= 65 and code <= 90) or (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code == 95

static func _load_terms() -> void:
	if _terms_ready:
		return
	var tree = Engine.get_main_loop() as SceneTree
	var loc = tree.root.get_node_or_null("Localization") if tree != null else null
	if loc == null:
		return
	var tables: Variant = loc.get("_translations")
	if not tables is Dictionary or not tables.has("en") or not tables.has("ko"):
		return
	var english: Dictionary = tables.en
	var korean: Dictionary = tables.ko
	var ambiguous := {}
	var ability_ambiguous := {}
	var ability_sources := {}
	for key in english:
		if not korean.has(key):
			continue
		var source := str(english[key]).strip_edges().to_lower()
		var translated := str(korean[key]).strip_edges()
		if source.is_empty() or source == translated.to_lower():
			continue
		if _terms.has(source) and _terms[source] != translated:
			ambiguous[source] = true
		else:
			_terms[source] = translated
		if str(key).begins_with("ui.ability."):
			ability_sources[source] = true
			if _ability_terms.has(source) and _ability_terms[source] != translated:
				ability_ambiguous[source] = true
			else:
				_ability_terms[source] = translated
	for source in ambiguous:
		_terms.erase(source)
	for source in ability_ambiguous:
		_ability_terms.erase(source)
	for source in ABILITY_ALIASES:
		if ability_sources.has(source):
			_ability_terms[source] = ABILITY_ALIASES[source]
	_terms_ready = true

static func term(value: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	_load_terms()
	return str(_terms.get(original.strip_edges().to_lower(), original))

static func ability(value: Variant) -> String:
	var original := str(value)
	if not Names._is_korean():
		return original
	_load_terms()
	return str(_ability_terms.get(original.strip_edges().to_lower(), term(original)))
