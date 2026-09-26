"""Local estimate from the user-supplied official V4 archive, never a bill bound."""

import hashlib
import io
import json
from pathlib import Path
import zipfile

from backend.errors import ApiError


TOKENIZER_SOURCE = 'https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip'
TOKENIZER_SHA256 = 'e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495'
TOKENIZER_PATH = Path(__file__).resolve().parents[1] / 'storage/model/deepseek_v4_tokenizer.zip'
INPUT_REFERENCE = f'local-chat-template-estimate; {TOKENIZER_SOURCE}; sha256={TOKENIZER_SHA256}'


def estimate_input_tokens(messages, *, tokenizer_path=TOKENIZER_PATH):
    """Render the pinned local chat template; no download or bundled Python execution.

    Provider-side templates/JSON-mode overhead may differ. This is deliberately
    an estimate, per D-21, not a proven upper bound on prompt_tokens.
    """
    try:
        from jinja2.sandbox import SandboxedEnvironment
        from tokenizers import Tokenizer

        with Path(tokenizer_path).open('rb') as source:
            archive = source.read(10_000_001)
        if hashlib.sha256(archive).hexdigest() != TOKENIZER_SHA256:
            raise ValueError('Tokenizer archive does not match the reviewed material')
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            config = json.loads(bundle.read('deepseek_v4_tokenizer/tokenizer_config.json'))
            tokenizer = Tokenizer.from_str(bundle.read('deepseek_v4_tokenizer/tokenizer.json').decode('utf-8'))
        template = SandboxedEnvironment().from_string(config['chat_template'])
        prompt = template.render(messages=messages, bos_token=config['bos_token']['content'],
                                 add_generation_prompt=True)
        return len(tokenizer.encode(prompt).ids)
    except (ImportError, OSError, ValueError, zipfile.BadZipFile):
        raise ApiError(503, 'MODEL_TOKENIZER_UNAVAILABLE',
                       '本地 tokenizer 文件或依赖不可用，请核对已登记的版本与文件摘要') from None
