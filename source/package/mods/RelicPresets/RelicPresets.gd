extends RefCounted
## Optional lineup equipment presets. Stores owned instance IDs, never resources.
const KEY = "eslabong_mod_relic_preset"
const OPTION = "eslabong_mod_include_relics"
const RESULT = "eslabong_mod_relic_result"
const PLACEMENT = ["state", "inventory_slot", "equipped_fighter_id", "equipped_slot", "local_listing_id", "quarantine_reason", "capacity_locked"]

static func _campaign():
	var tree = Engine.get_main_loop()
	return tree.root.get_node_or_null("CampaignService") if tree is SceneTree else null

static func _ko() -> bool:
	var tree = Engine.get_main_loop()
	var loc = tree.root.get_node_or_null("Localization") if tree is SceneTree else null
	return loc != null and loc.get_current_locale() == "ko"

static func _text(ko: String, en: String) -> String:
	return ko if _ko() else en

static func attach(screen, content, hint) -> void:
	content.add_child(hint)
	hint.text = _text("주전 5명을 저장합니다. 아래 항목을 체크하면 유물 장비도 함께 저장하고 불러옵니다.", "Save five Active fighters. Check below to also save and restore their relic equipment.")
	var check = CheckBox.new()
	check.name = "IncludeRelicsInPreset"
	check.text = _text("유물도 함께 저장·불러오기", "Include relic equipment when saving/loading")
	check.tooltip_text = _text("보유 중인 개별 유물을 이동합니다. 없어진 유물은 만들지 않습니다. 기존 슬롯은 체크 후 한 번 덮어써 주세요. 유물 포함 불러오기는 되돌리기 없이 적용됩니다.", "Moves owned item instances only. Missing items are not created. Overwrite old slots once with this checked. Relic loads do not offer Undo.")
	check.add_theme_font_override("font", hint.get_theme_font("font"))
	check.add_theme_font_size_override("font_size", hint.get_theme_font_size("font_size"))
	var campaign = _campaign()
	var save = campaign.current_save if campaign != null else null
	check.button_pressed = bool(save.get_meta(OPTION, false)) if save != null else false
	screen.set_meta(OPTION, check.button_pressed)
	check.toggled.connect(func(value):
		screen.set_meta(OPTION, value)
		if save != null:
			save.set_meta(OPTION, value)
	)
	content.add_child(check)

static func capture(save, ids: Array) -> Dictionary:
	var fighters = {}
	for id in ids:
		var fighter = save.get_mercenary_by_id(str(id))
		if fighter != null:
			fighters[str(id)] = [fighter.get_equipped_item_instance_id(0), fighter.get_equipped_item_instance_id(1)]
	return {"schema": 1, "fighters": fighters}

static func popup_size(content) -> Vector2i:
	return Vector2i(704, maxi(482, int(content.get_combined_minimum_size().y) + 24))

static func capture_preset(screen, save, preset: Dictionary) -> Dictionary:
	if bool(screen.get_meta(OPTION, false)):
		preset[KEY] = capture(save, preset.get("deployed", []))
	return preset

static func _snapshot(save) -> Dictionary:
	var result = {"items": [], "fighters": [], "new": save.item_new_instance_ids.duplicate()}
	for item in save.owned_item_instances:
		if item == null:
			continue
		var fields = {}
		for field in PLACEMENT:
			fields[field] = item.get(field)
		result.items.append([item, fields])
	for fighter in save.owned_mercenaries:
		if fighter != null:
			result.fighters.append([fighter, fighter.equipped_item_instance_ids.duplicate(), fighter.equipped_relics.duplicate()])
	return result

static func _rollback(save, snapshot: Dictionary) -> void:
	for row in snapshot.items:
		for field in PLACEMENT:
			row[0].set(field, row[1][field])
	for row in snapshot.fighters:
		row[0].equipped_item_instance_ids.assign(row[1])
		row[0].equipped_relics.assign(row[2])
	save.item_new_instance_ids.assign(snapshot.new)

static func audit(save, capacity: int = -1) -> String:
	var items = {}
	var locations = {}
	var fighter_ids = {}
	for fighter in save.owned_mercenaries:
		if fighter == null:
			continue
		if fighter.instance_id == "" or fighter_ids.has(fighter.instance_id):
			return "duplicate_fighter_id"
		fighter_ids[fighter.instance_id] = fighter
	for item in save.owned_item_instances:
		if item == null:
			continue
		if item.instance_id == "" or items.has(item.instance_id):
			return "duplicate_item_id"
		items[item.instance_id] = item
		if item.is_equipped():
			var fighter = fighter_ids.get(item.equipped_fighter_id)
			if fighter == null or item.equipped_slot < 0 or item.equipped_slot >= 2:
				return "invalid_item_owner"
			if fighter.get_equipped_item_instance_id(item.equipped_slot) != item.instance_id:
				return "item_slot_mismatch"
		elif item.is_in_inventory():
			if item.inventory_slot < 0 or locations.has(item.inventory_slot):
				return "invalid_inventory_slot"
			if capacity >= 0 and not item.capacity_locked and item.inventory_slot >= capacity:
				return "inventory_capacity_exceeded"
			locations[item.inventory_slot] = true
	var equipped = {}
	for fighter in save.owned_mercenaries:
		if fighter == null:
			continue
		for slot in range(2):
			var id = fighter.get_equipped_item_instance_id(slot)
			if id == "":
				continue
			var item = items.get(id)
			if equipped.has(id) or item == null or not item.is_equipped():
				return "invalid_equipped_item"
			if item.equipped_fighter_id != fighter.instance_id or item.equipped_slot != slot:
				return "fighter_slot_mismatch"
			equipped[id] = true
	return ""

static func apply_loadout(save, inventory, loadout, active_ids: Array, locked_ids: Array = []) -> Dictionary:
	# No await, no item construction, and no signals until the complete transaction commits.
	if not loadout is Dictionary or loadout.get("schema") != 1 or not loadout.get("fighters") is Dictionary:
		return {"ok": false, "error": "invalid_preset"}
	var problem = audit(save, inventory._active_capacity())
	if problem != "":
		return {"ok": false, "error": problem}
	var changes = []
	var claims = {}
	var skipped = 0
	for fighter_id in active_ids:
		var fighter = save.get_mercenary_by_id(str(fighter_id))
		if fighter == null or not loadout.fighters.has(str(fighter_id)):
			continue
		var slots = loadout.fighters[str(fighter_id)]
		if not slots is Array or slots.size() != 2:
			return {"ok": false, "error": "invalid_preset_slots"}
		for slot in range(2):
			if not slots[slot] is String:
				return {"ok": false, "error": "invalid_item_id"}
			var id: String = slots[slot]
			if id != "":
				if claims.has(id):
					return {"ok": false, "error": "duplicate_preset_item"}
				claims[id] = true
			var previous: String = fighter.get_equipped_item_instance_id(slot)
			if id == previous:
				continue
			if locked_ids.has(str(fighter_id)) or not fighter.is_relic_slot_unlocked(slot):
				skipped += 1
				continue
			if id != "":
				var item = inventory.find_item(id)
				if item == null or item.capacity_locked or (not item.is_in_inventory() and not item.is_equipped()):
					skipped += 1
					continue
				if item.is_equipped() and locked_ids.has(item.equipped_fighter_id):
					skipped += 1
					continue
				var definition = inventory._catalog.get_definition(item.definition_id)
				if definition == null or not definition.enabled or not definition.is_compatible_with(fighter):
					skipped += 1
					continue
			changes.append([str(fighter_id), slot, id])
	var before = _snapshot(save)
	var owned_identity = save.owned_item_instances.duplicate()
	var blocked: bool = inventory.is_blocking_signals()
	inventory.set_block_signals(true)
	var detach = {}
	for row in changes:
		detach[row[0] + ":" + str(row[1])] = [row[0], row[1]]
		if row[2] != "":
			var item = inventory.find_item(row[2])
			if item.is_equipped():
				detach[item.equipped_fighter_id + ":" + str(item.equipped_slot)] = [item.equipped_fighter_id, item.equipped_slot]
	for row in detach.values():
		var result: Dictionary = inventory.unequip(row[0], row[1])
		if not result.get("ok", false):
			problem = str(result.get("error", "unequip_failed"))
			break
	if problem == "":
		for row in changes:
			if row[2] == "":
				continue
			var result: Dictionary = inventory.equip(row[2], row[0], row[1])
			if not result.get("ok", false):
				problem = str(result.get("error", "equip_failed"))
				break
	if problem == "":
		problem = audit(save, inventory._active_capacity())
	if problem == "" and save.owned_item_instances != owned_identity:
		problem = "owned_items_changed"
	if problem == "":
		var ids: Array[String] = []
		ids.assign(active_ids)
		var valid: Dictionary = inventory.validate_lineup_relics(ids)
		if not valid.get("ok", false):
			problem = str(valid.get("error", "illegal_lineup"))
	if problem != "":
		_rollback(save, before)
		inventory.set_block_signals(blocked)
		return {"ok": false, "error": problem}
	inventory.set_block_signals(blocked)
	return {"ok": true, "changed": changes.size(), "skipped": skipped, "rollback": before}

static func commit(screen, slot_index: int) -> bool:
	screen.set_meta(RESULT, {})
	var campaign = _campaign()
	if campaign == null or campaign.current_save == null:
		return false
	var save = campaign.current_save
	var preset: Dictionary = save.get_saved_active_lineup(slot_index)
	if not bool(screen.get_meta(OPTION, false)) or not preset.has(KEY):
		if bool(screen.get_meta(OPTION, false)):
			screen.set_meta(RESULT, {"legacy": true})
		return screen._commit_pending_lineup_changes()
	var ids: Array[String] = screen._normalize_pending_deployment(screen.pending_deployment, save)
	var base_inventory = campaign.get_inventory_service()
	if base_inventory == null:
		screen._show_roster_toast(_text("유물 보관함을 불러오지 못해 프리셋을 적용하지 않았습니다.", "Inventory unavailable; preset not applied."))
		return false
	var inventory = base_inventory.for_active_lineup(ids)
	var locked: Array = []
	for method in ["get_academy_match_locked_fighter_ids", "get_barracks_focused_training_mercenary_ids"]:
		if campaign.has_method(method):
			locked.append_array(campaign.call(method))
	var result = apply_loadout(save, inventory, preset[KEY], ids, locked)
	if not result.get("ok", false):
		screen.refresh_ui()
		screen._show_roster_toast(_text("유물 프리셋을 적용하지 않았습니다. 기존 장비와 주전은 유지됩니다: ", "Relic preset not applied; equipment and lineup unchanged: ") + str(result.get("error")))
		return false
	if not screen._commit_pending_lineup_changes():
		_rollback(save, result.rollback)
		screen.refresh_ui()
		return false
	result.erase("rollback")
	screen.set_meta(RESULT, result)
	if result.changed > 0:
		inventory.inventory_changed.emit("relic_preset")
	return true

static func message(screen, original: String) -> String:
	var result: Dictionary = screen.get_meta(RESULT, {})
	if result.get("legacy", false):
		return original + _text(" · 유물 기록 없음: 체크 후 슬롯을 다시 저장하세요", " · No relic snapshot: overwrite this slot with the option checked")
	if not result.get("ok", false):
		return original
	return original + (_text(" · 유물 %d칸 변경 / %d칸 건너뜀", " · Relics: %d slots changed / %d skipped") % [result.changed, result.skipped])

static func undo(screen, original: Dictionary) -> Dictionary:
	# Avoid offering base game's lineup-only Undo after equipment has moved.
	return {} if screen.get_meta(RESULT, {}).get("ok", false) else original
