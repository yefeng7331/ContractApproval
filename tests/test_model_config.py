"""Offline smoke test; only fake credentials in a temporary directory."""

import tempfile
import traceback
import unittest
from pathlib import Path

from backend.model_config import CONFIG_PATH, load_api_key


class ModelConfigTests(unittest.TestCase):
    def test_local_key_loading(self):
        self.assertEqual(CONFIG_PATH, Path(__file__).resolve().parents[1] / 'secrets' / 'deepseek.ini')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.ini'
            with self.assertRaises(ValueError):
                load_api_key(path)
            path.write_text('[deepseek]\napi_key = fake-test-key%123\n', encoding='utf-8-sig')
            self.assertEqual(load_api_key(path), 'fake-test-key%123')
            for content in ('[deepseek]\napi_key =\n', '[other]\napi_key = fake-secret\n',
                            '[deepseek]\napi_key = "fake-secret"\n',
                            '[deepseek]\napi_key = fake secret\n',
                            '[deepseek]\nfake-secret\n',
                            '[deepseek]\napi_key = first\napi_key = fake-secret\n'):
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    try:
                        load_api_key(path)
                    except ValueError:
                        self.assertNotIn('fake-secret', traceback.format_exc())
                    else:
                        self.fail('Invalid configuration was accepted')


if __name__ == '__main__':
    unittest.main()
