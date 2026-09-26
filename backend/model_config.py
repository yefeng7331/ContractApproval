"""Read the project-local API key without changing environment variables."""

import configparser
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[1] / 'secrets' / 'deepseek.ini'


def load_api_key(path=CONFIG_PATH):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with Path(path).open(encoding='utf-8-sig') as source:
            config.read_file(source)
        key = config.get('deepseek', 'api_key').strip()
        if not key or any(not 33 <= ord(c) <= 126 or c in '\"\'' for c in key):
            raise ValueError
    except (OSError, UnicodeError, configparser.Error, ValueError):
        # Parser errors may contain the key; never include their raw text.
        raise ValueError('DeepSeek local configuration missing or invalid') from None
    return key


if __name__ == '__main__':
    try:
        load_api_key()
    except ValueError:
        print('DeepSeek key not configured: edit secrets/deepseek.ini (no quotes).')
        raise SystemExit(1)
    print('DeepSeek key loaded locally; no API call made.')
