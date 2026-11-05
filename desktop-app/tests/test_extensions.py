from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest

import extensions
import tools_registry


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.data=patch.object(extensions,'data_root',return_value=self.root/'managed');self.data.start()
        self.external=self.root/'external';self.external.mkdir()
        self.roots=patch.object(extensions,'roots',return_value=[('Codex',self.external)]);self.roots.start()

    def tearDown(self):self.roots.stop();self.data.stop();self.tmp.cleanup()

    def skill(self,name='example',body='Use a local helper.'):
        folder=self.external/name;folder.mkdir()
        (folder/'SKILL.md').write_text('---\nname: '+name+'\ndescription: Local test skill.\n---\n'+body)
        return extensions.describe(folder/'SKILL.md','Codex')

    def test_twelve_builtin_skills_enabled_on_fresh_install(self):
        skills=extensions.list_skills()['skills']
        self.assertEqual(len(skills),12)
        self.assertTrue(all(x['enabled'] and x['installed'] for x in skills))
        self.assertEqual(extensions.list_skills()['plugins'][0]['name'],'Syntra Essentials')

    def test_discovery_does_not_install_or_modify_source(self):
        item=self.skill();original=Path(item['path']).read_bytes()
        found=extensions.list_skills(discover=True)['skills']
        self.assertFalse(next(x for x in found if x['id']==item['id'])['installed'])
        self.assertFalse((self.root/'managed').exists())
        self.assertEqual(Path(item['path']).read_bytes(),original)

    def test_import_copies_resources_and_starts_disabled(self):
        item=self.skill();folder=Path(item['path']).parent
        (folder/'references').mkdir();(folder/'references/info.md').write_text('Resource evidence 7258')
        imported=extensions.install_skill(item['id'])
        self.assertFalse(imported['enabled'])
        self.assertIn('7258',(Path(imported['path']).parent/'references/info.md').read_text())
        with self.assertRaises(ValueError):extensions.read_skill(item['id'])
        extensions.enable_skill(item['id'],True)
        self.assertIn('local helper',extensions.read_skill(item['id'])['output'])

    def test_import_is_idempotent_and_source_edits_do_not_replace_copy(self):
        item=self.skill();installed=extensions.install_skill(item['id'])
        Path(item['path']).write_text('Changed external instructions')
        extensions.install_skill(item['id'])
        self.assertIn('local helper',Path(installed['path']).read_text())

    def test_disabled_builtin_blocks_native_reader(self):
        item=next(x for x in extensions.list_skills()['skills'] if x['name']=='pdf-reader')
        extensions.enable_skill(item['id'],False)
        result=tools_registry.execute_tool('read_document',{'path':'example.pdf'},{})
        self.assertFalse(result['success'])
        self.assertIn('Enable pdf-reader',result['output'])

    def test_missing_catalog_id_and_uninstalled_enable_fail(self):
        with self.assertRaises(ValueError):extensions.install_skill('not-a-real-id')
        with self.assertRaises(ValueError):extensions.enable_skill('not-a-real-id',True)

    def test_plugin_copies_skills_without_executing_scripts(self):
        plugin=self.root/'plugin';skill=plugin/'skills/example';skill.mkdir(parents=True)
        (plugin/'plugin.json').write_text(json.dumps({'name':'Example plugin','skills':['skills']}))
        (skill/'SKILL.md').write_text('---\nname: example\ndescription: Plugin skill.\n---\nRead sources.')
        (skill/'helper.py').write_text('raise RuntimeError("must not run at import")')
        result=extensions.import_plugin(plugin)
        self.assertEqual(len(result['skills']),1)
        self.assertFalse(extensions.state()['skills'][result['skills'][0]]['enabled'])
        self.assertEqual(extensions.import_plugin(plugin)['id'],result['id'])

    def test_plugin_path_escape_is_rejected_without_install(self):
        plugin=self.root/'plugin';plugin.mkdir()
        (plugin/'plugin.json').write_text(json.dumps({'name':'Bad','skills':['../external']}))
        with self.assertRaises(ValueError):extensions.import_plugin(plugin)
        self.assertEqual(extensions.state()['plugins'],{})

    def test_bundle_limits_and_secret_filename_exclusion(self):
        item=self.skill();folder=Path(item['path']).parent
        (folder/'.env').write_text('TEST_SECRET=do-not-copy')
        (folder/'mcp_config.json').write_text('{"token":"do-not-copy"}')
        installed=extensions.install_skill(item['id'])
        dest=Path(installed['path']).parent
        self.assertFalse((dest/'.env').exists());self.assertFalse((dest/'mcp_config.json').exists())
        second=self.skill('large');large=Path(second['path']).parent/'large.bin'
        with large.open('wb') as stream:stream.truncate(26*1024*1024)
        with self.assertRaises(ValueError):extensions.install_skill(second['id'])
        self.assertNotIn(second['id'],extensions.state()['skills'])

    def test_catalog_guidance_is_bounded_and_only_enabled(self):
        item=self.skill(body='External guidance');extensions.install_skill(item['id'])
        self.assertNotIn(item['id'],extensions.prompt_catalog())
        extensions.enable_skill(item['id'],True)
        self.assertIn(item['id'],extensions.prompt_catalog())
        self.assertLess(len(extensions.prompt_catalog()),5500)


if __name__=='__main__':unittest.main()
