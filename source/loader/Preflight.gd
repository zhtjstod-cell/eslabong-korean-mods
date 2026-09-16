extends Node
func _ready():
	var config = JSON.parse_string(FileAccess.get_file_as_string("res://EslabongLoader/boot.json"))
	var good = true
	for path in config.get("verify_resources", {}):
		var actual = FileAccess.get_sha256("res://" + path)
		if actual != config.verify_resources[path]:
			printerr("OVERLAY_RESOURCE_MISMATCH ", path)
			good = false
	print("EXTERNAL_PREFLIGHT_RESULT ", "OK" if good else "FAILED")
	get_tree().quit(0 if good else 72)
