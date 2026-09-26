"""Isolated CPU OCR process. Models must already exist; never download on upload."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'storage' / 'ocr'


def create_engine():
    os.environ['USERPROFILE'] = str(CACHE / 'profile')
    for name, directory in {'PADDLE_PDX_CACHE_HOME': 'paddlex',
        'PADDLE_EXTENSION_DIR': 'extensions', 'HF_HOME': 'huggingface',
        'MODELSCOPE_CACHE': 'modelscope'}.items():
        os.environ[name] = str(CACHE / directory)
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    models = CACHE / 'paddlex' / 'official_models'
    names = ('PP-OCRv5_mobile_det', 'PP-OCRv5_mobile_rec')
    if not all((models / name / 'inference.pdiparams').is_file() for name in names):
        raise FileNotFoundError('Local OCR models missing')
    from paddleocr import PaddleOCR

    # Windows oneDNN rejects this model's PIR attributes; plain CPU is verified.
    return PaddleOCR(device='cpu', cpu_threads=4, enable_mkldnn=False,
        text_detection_model_name=names[0], text_detection_model_dir=str(models / names[0]),
        text_recognition_model_name=names[1], text_recognition_model_dir=str(models / names[1]),
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, text_rec_score_thresh=0.0)


def main():
    import numpy as np
    from PIL import Image

    engine = create_engine()
    pages = []
    with Image.open(sys.argv[1]) as image:
        for index in range(image.n_frames):
            image.seek(index)
            result = list(engine.predict(np.array(image.convert('RGB'))[:, :, ::-1]))[0]
            pages.append({'width': image.width, 'height': image.height,
                'texts': list(result['rec_texts']),
                'scores': [float(value) for value in result['rec_scores']],
                'boxes': result['rec_boxes'].tolist()})
    Path(sys.argv[2]).write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
