"""Run the isolated CPU OCR runtime on synthetic samples; no application DB/model API."""

import json
import os
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'storage' / 'ocr'
# Paddle imports legacy dataset modules that ignore its dedicated cache options.
# Isolate this OCR process's Windows profile; do not change the machine profile.
profile = CACHE / 'profile'
profile.mkdir(parents=True, exist_ok=True)
os.environ['USERPROFILE'] = str(profile)
for name, subdir in {
    'PADDLE_PDX_CACHE_HOME': 'paddlex', 'PADDLE_EXTENSION_DIR': 'extensions',
    'HF_HOME': 'huggingface', 'MODELSCOPE_CACHE': 'modelscope',
}.items():
    os.environ[name] = str(CACHE / subdir)
os.environ['PADDLE_PDX_MODEL_SOURCE'] = 'bos'


def main():
    from paddleocr import PaddleOCR
    from PIL import Image, ImageDraw

    started = time.monotonic()
    # Windows Paddle 3.3.1 oneDNN rejects a model PIR attribute; plain CPU works.
    engine = PaddleOCR(device='cpu', cpu_threads=4, enable_mkldnn=False,
        text_detection_model_name='PP-OCRv5_mobile_det',
        text_recognition_model_name='PP-OCRv5_mobile_rec',
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False)
    output = ROOT / 'storage' / 'verification' / 'ocr'
    output.mkdir(parents=True, exist_ok=True)
    oracle = json.loads((ROOT / 'samples' / 'f1_f4_expected.json').read_text(encoding='utf-8'))
    expected = [row[3] for row in oracle['samples']['F1']['paragraphs']]
    fixture = json.loads((ROOT / 'samples' / 'f3_expected.json').read_text(encoding='utf-8'))
    summary = []
    for filename in ('f3-clear-scan.png', 'f5-blurred-scan.png'):
        before = time.monotonic()
        results = list(engine.predict(str(ROOT / 'samples' / filename)))
        if len(results) != 1:
            raise RuntimeError('Expected one page')
        results[0].save_to_json(str(output / (Path(filename).stem + '.json')))
        result = results[0]
        texts = list(result['rec_texts'])
        if filename.startswith('f3'):
            # Comparison only: never rewrite OCR output with fixture answers.
            compare = lambda text: ''.join(unicodedata.normalize('NFKC', text).split())
            assert len(texts) == len(expected) == 12, 'F3 line count changed'
            assert all(compare(a) == compare(b) for a, b in zip(texts, expected)), 'F3 text mismatch'
            canvas = Image.open(ROOT / 'samples' / filename).convert('RGB')
            draw = ImageDraw.Draw(canvas)
            overlaps = []
            for box, (_, left, top, right, bottom) in zip(result['rec_boxes'], fixture['paragraph_boxes']):
                x1, y1, x2, y2 = map(int, box)
                assert 0 <= x1 < x2 <= canvas.width and 0 <= y1 < y2 <= canvas.height
                intersection = max(0, min(x2, right) - max(x1, left)) * max(0, min(y2, bottom) - max(y1, top))
                union = (x2-x1)*(y2-y1) + (right-left)*(bottom-top) - intersection
                overlaps.append(intersection / union)
                assert overlaps[-1] >= 0.65, 'F3 box differs from independent annotation'
                draw.rectangle((x1, y1, x2, y2), outline='red', width=3)
            assert len(result['rec_boxes']) == 12
            canvas.save(output / 'f3-location-overlay.png')
            summary.append({'sample': 'F3', 'lines': len(texts), 'comparison': 'NFKC, ignore whitespace',
                'exact_lines': sum(a == b for a, b in zip(texts, expected)),
                'minimum_box_iou': round(min(overlaps), 4)})
        else:
            assert texts == [], 'F5 severe blur unexpectedly recognized text; inspect before accepting'
            summary.append({'sample': 'F5', 'lines': 0})
        print(json.dumps({'file': filename, 'lines': len(result['rec_texts']),
            'texts': result['rec_texts'], 'scores': [float(x) for x in result['rec_scores']],
            'seconds': round(time.monotonic() - before, 3)}, ensure_ascii=False), flush=True)
    print(json.dumps({'total_seconds': round(time.monotonic() - started, 3)}), flush=True)
    (output / 'verification-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
