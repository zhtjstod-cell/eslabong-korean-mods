"""Public relic-preset integration; contains no personal gameplay features."""
from structural_hooks import require_members,require_calls
from relic_hooks import connect,remove
TARGET='UI/screens/myteam_screen.gdc'
HELPER='RelicPresets/RelicPresets.gd'
R='preload("res://'+HELPER+'").'
RULES=[
 ('_show_save_active_popup','content.add_child(hint)',R+'attach(self,content,hint)'),
 ('_save_current_active_to_slot','save.set_saved_active_lineup(slot_index,{','save.set_saved_active_lineup(slot_index,'+R+'capture_preset(self,save,{'),
 ('_save_current_active_to_slot','})','}))'),
 ('_on_saved_active_load_pressed','_commit_pending_lineup_changes()',R+'commit(self,slot_index)'),
 ('_on_saved_active_load_pressed','_show_roster_toast(message,undo_snapshot)','_show_roster_toast('+R+'message(self,message),'+R+'undo(self,undo_snapshot))'),
]
def validate_api(pack):
    # Check only interfaces actually used by the helper, never implementation
    # hashes or unrelated fields/constants. Native restrictions remain active.
    for path,fields in {
        'Scripts/Relics/InventoryService.gdc': ['inventory_changed','_catalog'],
        'Scripts/Relics/ItemInstance.gdc': ['instance_id','definition_id','state','inventory_slot','equipped_fighter_id','equipped_slot','local_listing_id','quarantine_reason','capacity_locked','rolled_modifiers','ownership_history'],
        'Scripts/Campaign/MercenaryInstance.gdc': ['instance_id','equipped_item_instance_ids','equipped_relics'],
        'Scripts/Campaign/CampaignSave.gdc': ['owned_item_instances','owned_mercenaries','item_new_instance_ids'],
        TARGET: ['pending_deployment'],
    }.items():require_members(pack,path,fields)
    require_calls(pack,'Scripts/Relics/InventoryService.gdc',{'for_active_lineup':1,'equip':3,'unequip':2,'find_item':1,'validate_lineup_relics':1,'_active_capacity':0})
    require_calls(pack,'Scripts/Relics/ItemInstance.gdc',{'is_equipped':0,'is_in_inventory':0})
    require_calls(pack,'Scripts/Campaign/MercenaryInstance.gdc',{'get_equipped_item_instance_id':1,'is_relic_slot_unlocked':1})
    require_calls(pack,'Scripts/Campaign/CampaignSave.gdc',{'get_mercenary_by_id':1,'get_saved_active_lineup':1,'set_saved_active_lineup':2})
    require_calls(pack,TARGET,{'_commit_pending_lineup_changes':0,'_normalize_pending_deployment':2,'_show_roster_toast':1,'refresh_ui':0})

def rewrite(data,rules=None,enable=True):
    # rules remains accepted for old build/test entry points; not used to match.
    return connect(data) if enable else remove(data)
