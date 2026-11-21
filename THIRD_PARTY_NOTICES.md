# Third-party components

This source package includes WAIE and inherited Scene Scribe code. It excludes
model weights, FFmpeg executables, Python environments and user recordings.
No blanket license is granted by this notice.

## Inherited source

[Scene Scribe](https://github.com/seki2020/scene-scribe), base commit
`e84d871387979918793537579412683039a1b11d`, supplies the original engine.
[LICENSE_STATUS.md](LICENSE_STATUS.md) records the outstanding permission.
Attribution does not replace an explicit grant.

## Installed dependencies

Direct dependencies are declared in [pyproject.toml](pyproject.toml). The
licenses/notices shipped with exact upstream versions apply separately and
should be retained when distributing those artifacts. This list identifies
components; it is not a replacement for their distribution notices.

| Component | Purpose | Upstream |
| --- | --- | --- |
| PySceneDetect / OpenCV | Scene detection and frames | [PySceneDetect](https://github.com/Breakthrough/PySceneDetect), [OpenCV](https://github.com/opencv/opencv) |
| faster-whisper / CTranslate2 | Speech recognition | [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2) |
| PyAV / FFmpeg | Media processing | [PyAV](https://github.com/PyAV-Org/PyAV), [FFmpeg](https://ffmpeg.org/legal.html) |
| PyTorch / torchvision | Model inference | [PyTorch](https://github.com/pytorch/pytorch), [torchvision](https://github.com/pytorch/vision) |
| Transformers / Hugging Face Hub | Model loading/downloads | [Transformers](https://github.com/huggingface/transformers), [Hub](https://github.com/huggingface/huggingface_hub) |
| Pillow, einops, timm | Image/model support | [Pillow](https://pypi.org/project/Pillow/), [einops](https://pypi.org/project/einops/), [timm](https://pypi.org/project/timm/) |
| FastAPI, Uvicorn, python-multipart | Web server/uploads | [FastAPI](https://pypi.org/project/fastapi/), [Uvicorn](https://pypi.org/project/uvicorn/), [python-multipart](https://pypi.org/project/python-multipart/) |
| Jinja2 / jsonschema | Templates/validation | [Jinja2](https://pypi.org/project/Jinja2/), [jsonschema](https://pypi.org/project/jsonschema/) |
| WeasyPrint (optional) | PDF exports | [WeasyPrint](https://github.com/Kozea/WeasyPrint) |

FFmpeg build options affect redistribution terms for its binaries. This source
expects a separately installed FFmpeg/ffprobe and does not bundle a binary.

## Downloaded models

- [Microsoft Florence-2-base](https://huggingface.co/microsoft/Florence-2-base)
  provides descriptions and model-specific code loaded by Transformers.
- [Systran faster-whisper-tiny](https://huggingface.co/Systran/faster-whisper-tiny)
  provides the converted speech-model weights.

`download_models.py` records resolved revisions and retains model cards and
license/notice files when provided. Consult those exact revisions before
redistributing weights. Downloads stay in ignored `models/` and are excluded
from the prepared source ZIP.
