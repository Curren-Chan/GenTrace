"""公開検査が誤ステージと未承認画像を拒否することを確認する。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('publication_audit',Path(__file__).resolve().parents[1]/'scripts/publication_audit.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicationAuditTests(unittest.TestCase):
    def test_db_signature_and_runtime_location_are_rejected(self):
        self.assertIn('private-binary',audit.check_content('sample.txt',b'SQLite format 3\0',{}))
        self.assertIn('private-directory',audit.check_content('data/private.txt',b'private',{}))
        self.assertIn('private-file-type',audit.check_content('copied.db-wal',b'wal',{}))

    def test_images_require_exact_reviewed_hash(self):
        name='docs/screenshots/viewer-demo.png'
        data=b'\x89PNG reviewed synthetic example'
        self.assertIn('unreviewed-image',audit.check_content(name,data,{}))
        hashes={name:hashlib.sha256(data).hexdigest()}
        self.assertEqual(audit.check_content(name,data,hashes),[])
        self.assertIn('unreviewed-image',audit.check_content(name,data+b'changed',hashes))

    def test_generated_secret_and_private_paths_are_detected(self):
        secret=b'ghp_'+b'A'*36
        self.assertIn('secret-key',audit.check_content('source.py',secret,{}))
        credential=json.dumps({'api_key':'A'*20}).encode()
        self.assertIn('credential-literal',audit.check_content('settings.example.json',credential,{}))
        # 本物の名前や認証情報をfixtureとして保存しない。
        path=b'/'.join((b'C:',b'Users',b'synthetic-person',b'image.png'))
        self.assertIn('personal-home-path',audit.check_content('source.py',path,{}))
        self.assertEqual(audit.check_content('config.example.json',b'{"stability_root":"C:/example/StabilityMatrix"}',{}),[])

    def test_staged_secret_is_found_after_worktree_has_been_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'docs/screenshots').mkdir(parents=True)
            (root/'docs/screenshots/manifest.json').write_text('{}')
            (root/'publication-files.txt').write_text('publication-files.txt\ndocs/screenshots/manifest.json\nsource.py\n')
            secret=b'ghp_'+b'A'*36
            (root/'source.py').write_bytes(secret)
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True,capture_output=True)
            (root/'source.py').write_text('safe_example = True\n')
            with patch.object(audit,'ROOT',root):
                self.assertTrue(audit.audit()['passed'])
                result=audit.audit(staged=True)
                self.assertFalse(result['passed'])
                self.assertEqual(result['findings'][0]['scope'],'index')
                self.assertNotIn(secret.decode(),json.dumps(result))
