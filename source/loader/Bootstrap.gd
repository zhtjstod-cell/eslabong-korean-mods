extends Node
## Runs before native autoloads. Only files prepared by the external launcher.
func _init():
	var config = JSON.parse_string(FileAccess.get_file_as_string("res://EslabongLoader/boot.json"))
	if not config is Dictionary:
		_fail("Loader configuration could not be read.")
		return
	if not ProjectSettings.load_resource_pack(str(config.base), false):
		_fail("The original game data could not be mounted.")
		return
	if not ProjectSettings.load_resource_pack(str(config.overlay), true):
		_fail("The prepared mod overlay could not be mounted.")
		return
	print("ESLABONG_EXTERNAL_LOADER_READY ", config.get("generation", ""))

func _fail(message):
	printerr("ESLABONG_EXTERNAL_LOADER_FAILED ", message)
	# No native autoload or game save has run yet. Never continue with half a
	# mounted game, and never terminate another process or an existing session.
	OS.kill(OS.get_process_id())
