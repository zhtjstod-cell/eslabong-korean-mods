"""No native game launch. Filesystem/cache/selection regression tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import public_mod_loader as loader
from external_pack import write_settings,read_settings,settings_string


class FakePack:
    def __init__(self,game):
        self.path=game/'eslabong.pck';self.stream=self.path.open('rb')


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='eslabong-loader-test-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.game=self.root/'한글 게임 폴더';self.game.mkdir()
        (self.game/'eslabong.exe').write_bytes(b'owned unchanged executable')
        (self.game/'eslabong.pck').write_bytes(b'owned unchanged pack')
        self.mods=self.root/'mods';folder=self.mods/'RelicPresets';folder.mkdir(parents=True)
        loader.atomic_json(folder/'mod.json',{'format':1,'id':'relic','enabled':True})
        (folder/'RelicPresets.gd').write_bytes(b'our payload')
        self.original={p.name:p.read_bytes() for p in self.game.iterdir()}
        self.patchers=[patch.object(loader,'Pack',FakePack),patch.object(loader,'ensure_closed'),
            patch.object(loader,'adapter_identity',return_value='test-loader'),
            patch.object(loader,'boot_files',return_value={'test.txt':b'boot'}),
            patch.object(loader,'probe',return_value={'ok':True}),
            patch.object(loader,'plan_overlay',side_effect=lambda p,en,found:({'mod.gd':json.dumps(en).encode()},{'enabled':en}))]
        self.mocks=[p.start() for p in self.patchers]
        for p in self.patchers:self.addCleanup(p.stop)

    def run_prepare(self,**options):return loader.prepare(self.game,self.mods,log=lambda x:None,**options)

    def assert_original(self):
        for name,data in self.original.items():self.assertEqual((self.game/name).read_bytes(),data)

    def test_roundtrip_opaque_settings(self):
        rows=[('unknown',b'opaque\0\1'),('autoload/A',settings_string('*res://a.gd'))]
        self.assertEqual(read_settings(write_settings(rows)),rows)

    def test_cache_hit_and_original_unchanged(self):
        exe,a=self.run_prepare();stamp=exe.stat().st_mtime_ns
        same,b=self.run_prepare()
        self.assertEqual(exe,same);self.assertTrue(b['cache_hit']);self.assertEqual(stamp,same.stat().st_mtime_ns)
        self.assertEqual(self.mocks[-1].call_count,1);self.assert_original()

    def test_game_update_invalidates(self):
        first,_=self.run_prepare();(self.game/'eslabong.pck').write_bytes(b'new game version')
        second,report=self.run_prepare()
        self.assertNotEqual(first,second);self.assertFalse(report['cache_hit'])
        self.assertEqual((self.game/'eslabong.pck').read_bytes(),b'new game version')

    def test_mod_update_invalidates(self):
        first,_=self.run_prepare();(self.mods/'RelicPresets/RelicPresets.gd').write_bytes(b'changed payload')
        second,report=self.run_prepare();self.assertNotEqual(first,second);self.assertFalse(report['cache_hit'])

    def test_selection_persists_and_removed_mod_disables(self):
        _,report=self.run_prepare(selected={'relic':False});self.assertFalse(report['enabled']['relic'])
        _,report=self.run_prepare();self.assertTrue(report['cache_hit']);self.assertFalse(report['enabled']['relic'])
        _,report=self.run_prepare(selected={'relic':True});self.assertTrue(report['enabled']['relic'])
        (self.mods/'RelicPresets').rename(self.root/'removed-relic')
        _,report=self.run_prepare();self.assertFalse(report['enabled']['relic'])

    def test_corrupt_cache_rebuilds(self):
        exe,_=self.run_prepare();exe.with_suffix('.pck').write_bytes(b'bad')
        second,report=self.run_prepare();self.assertNotEqual(exe,second);self.assertFalse(report['cache_hit'])

    def test_unsafe_cache_index_not_followed(self):
        _,report=self.run_prepare();index=self.mods/'EslabongCommunityLoader/cache'/report['generation']/'index.json'
        loader.atomic_json(index,{'directory':'../../outside'})
        _,report=self.run_prepare();self.assertFalse(report['cache_hit']);self.assert_original()

    def test_probe_failure_never_commits_or_changes_game(self):
        self.mocks[-2].side_effect=RuntimeError('intentional probe failure')
        with self.assertRaisesRegex(RuntimeError,'intentional'):self.run_prepare()
        self.assertFalse(list((self.mods/'EslabongCommunityLoader/cache').rglob('ready.json')));self.assert_original()
        self.mocks[-2].side_effect=None
        _,report=self.run_prepare();self.assertFalse(report['cache_hit'])

    def test_lock_release_and_exclusion(self):
        state=self.mods/'EslabongCommunityLoader'
        with loader.loader_lock(state):
            with self.assertRaises(RuntimeError):
                with loader.loader_lock(state):pass
        with loader.loader_lock(state):pass

    def test_mid_prepare_mod_update_rejected(self):
        self.mocks[-2].side_effect=lambda *args:(self.mods/'RelicPresets/RelicPresets.gd').write_bytes(b'update while preparing')
        with self.assertRaisesRegex(RuntimeError,'변경'):self.run_prepare()
        self.assertFalse(list((self.mods/'EslabongCommunityLoader/cache').rglob('ready.json')));self.assert_original()

    def test_launch_preserves_steam_checks_and_args(self):
        exe,report=self.run_prepare();report['inputs']['steam_app_id']=123
        with patch.object(loader.subprocess,'Popen') as call:
            loader.launch(exe,self.game,report,['--windowed'])
        self.assertEqual(call.call_args.args[0],[str(exe),'--windowed'])
        self.assertEqual(call.call_args.kwargs['env']['SteamAppId'],'123')
        self.assert_original()

    def test_public_mods_only(self):
        self.assertEqual(set(loader.MODULES),{'korean','relic'})
        folder=self.mods/'ShinyRebirth';folder.mkdir()
        loader.atomic_json(folder/'mod.json',{'format':1,'id':'rebirth','enabled':True})
        self.assertEqual(set(loader.modules(self.mods)),{'relic'})

    def test_portable_mod_root(self):
        with patch.object(loader,'distribution_root',return_value=self.root):
            self.assertEqual(loader.default_mod_root(self.game),self.mods)
        with patch.object(loader,'distribution_root',return_value=self.root/'elsewhere'):
            self.assertEqual(loader.default_mod_root(self.game),self.game/'mods')

    def test_missing_mods_is_clear_error(self):
        (self.mods/'RelicPresets').rename(self.root/'removed-relic')
        with self.assertRaisesRegex(ValueError,'모드 폴더'):self.run_prepare()

if __name__=='__main__':unittest.main(verbosity=2)
