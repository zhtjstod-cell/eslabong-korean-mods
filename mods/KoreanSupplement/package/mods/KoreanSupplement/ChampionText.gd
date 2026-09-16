extends RefCounted

# Exact reviewed fallback text only. Does not change configs, saves or identities.
const DATA_PATH := "res://KoreanSupplement/champion_text.json"
static var _translations: Dictionary = {}
static var _loaded := false

static func _normal(value: String) -> String:
	return " ".join(value.replace("\r", " ").replace("\n", " ").replace("\t", " ").split(" ", false))

static func text(original: String) -> String:
	if not preload("res://KoreanSupplement/PersonalNames.gd")._is_korean():
		return original
	if not _loaded:
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(DATA_PATH))
		if parsed is Dictionary:
			for row in parsed.values():
				if row is Dictionary and row.get("en") is String and row.get("after") is String:
					_translations[_normal(row["en"])] = row["after"]
		_loaded = true
	return str(_translations.get(_normal(original), original))
