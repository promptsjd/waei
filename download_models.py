"""Download editor vision/speech models and record their exact revisions."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('HF_HOME', str(ROOT / 'models' / '.hf-cache'))
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

from huggingface_hub import HfApi, snapshot_download

repo = 'microsoft/Florence-2-base'
revision = HfApi().model_info(repo).sha
destination = ROOT / 'models' / 'Florence-2-base'
snapshot_download(repo, revision=revision, local_dir=destination,
                  allow_patterns=['*.json', '*.py', '*.safetensors', '*.txt', '*.model', 'LICENSE*', 'COPYING*', 'NOTICE*', 'README.md'],
                  max_workers=3)
(ROOT / 'models' / 'revision.json').write_text(
    json.dumps({'repository': repo, 'revision': revision}, indent=2), encoding='utf-8')
print('Downloaded model:', destination, 'revision:', revision)
asr_repo = 'Systran/faster-whisper-tiny'
asr_revision = HfApi().model_info(asr_repo).sha
snapshot_download(asr_repo, revision=asr_revision,
                  local_dir=ROOT / 'models' / 'faster-whisper-tiny',
                  allow_patterns=['*.json', '*.bin', '*.txt', 'LICENSE*', 'COPYING*', 'NOTICE*', 'README.md'], max_workers=3)
(ROOT / 'models' / 'whisper-revision.json').write_text(
    json.dumps({'repository': asr_repo, 'revision': asr_revision}, indent=2), encoding='utf-8')
print('Tiny speech model ready.')
