extends RefCounted

const DATA_PATH := "res://KoreanSupplement/personal_names.json"
const CUSTOM_META := "korean_name_user_override"
static var _data: Dictionary = {}
static var _cache: Dictionary = {}

static func _is_korean() -> bool:
	var tree = Engine.get_main_loop() as SceneTree
	if tree == null:
		return false
	var localization = tree.root.get_node_or_null("Localization")
	return localization != null and localization.get_current_locale() == "ko"

static func _load_data() -> void:
	if not _data.is_empty():
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
	if parsed is Dictionary:
		_data = parsed

static func name_of(fighter: Variant) -> String:
	if fighter == null:
		return ""
	var original: String = str(fighter.display_name)
	if fighter is Object and fighter.has_meta(CUSTOM_META) and bool(fighter.get_meta(CUSTOM_META)):
		return original
	return text(original)

static func text(original: String) -> String:
	if not _is_korean() or original.is_empty():
		return original
	_load_data()
	if _data.is_empty():
		return original
	if _cache.has(original):
		return _cache[original]
	var first_names: Dictionary = _data.get("names", {})
	var fixed_names: Dictionary = _data.get("fixed", {})
	var titles: Dictionary = _data.get("titles", {})
	var result := original
	if first_names.has(original):
		result = first_names[original]
	elif fixed_names.has(original):
		result = fixed_names[original]
	else:
		for title in titles:
			var ending: String = " " + str(title)
			if not original.ends_with(ending):
				continue
			var first: String = original.substr(0, original.length() - ending.length())
			if first_names.has(first):
				result = str(titles[title]) + " " + str(first_names[first])
				break
	if _cache.size() < 20000:
		_cache[original] = result
	return result

static func accept_name(fighter: Object, entered: String) -> String:
	# Merely saving the displayed Korean name must not overwrite its original.
	if entered == name_of(fighter) or entered == str(fighter.display_name):
		return str(fighter.display_name)
	fighter.set_meta(CUSTOM_META, true)
	return entered
