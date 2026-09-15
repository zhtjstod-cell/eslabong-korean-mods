"""Public relic-preset integration; contains no personal gameplay features."""
from structural_hooks import rewrite,require_members,require_calls
from relic_contract import ROOTS
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
    for path,fields in ROOTS.items():require_members(pack,path,fields)
    require_members(pack,'Scripts/Relics/ItemInstance.gdc',['ownership_history'])
    require_calls(pack,'Scripts/Relics/InventoryService.gdc',{'for_active_lineup':1,'equip':3,'unequip':2,'find_item':1,'validate_lineup_relics':1,'_active_capacity':0})
    require_calls(pack,TARGET,{'_commit_pending_lineup_changes':0,'_normalize_pending_deployment':2})
