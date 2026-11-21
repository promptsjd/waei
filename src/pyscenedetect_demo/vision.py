from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from pyscenedetect_demo.settings import AppSettings, DEFAULT_MODELS


def describe_images_with_florence(
    *,
    image_paths: list[Path],
    model_name: str,
    task_prompt: str = DEFAULT_MODELS.caption_task,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    settings: AppSettings | None = None,
) -> list[str]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "torch is not installed. Install a CPU build first, then reinstall `.[vision]`."
        ) from exc

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is not installed. Install it in .venv before running visual descriptions."
        ) from exc

    try:
        from transformers import AutoModelForCausalLM, AutoProcessor
    except ImportError as exc:
        raise RuntimeError(
            "transformers is not installed. Reinstall dependencies with `pip install -e '.[vision]'`."
        ) from exc

    settings = settings or AppSettings.from_env()
    device = settings.models.device
    torch_dtype = torch.float32
    model_name = settings.vision_model_path(model_name)
    torch.set_num_threads(min(torch.get_num_threads(), settings.models.cpu_threads))
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
            attn_implementation="eager",
        ).to(device)
        model.eval()
        processor = AutoProcessor.from_pretrained(
            model_name,
            trust_remote_code=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to load Florence-2 model `{model_name}`: {exc}") from exc

    total = len(image_paths)
    descriptions: list[str] = []
    for i, image_path in enumerate(image_paths, start=1):
        if progress_callback:
            progress_callback("describing", i, total, f"Scene {i}/{total}")
        try:
            image = Image.open(image_path).convert("RGB")
            inputs = processor(
                text=task_prompt,
                images=image,
                return_tensors="pt",
            ).to(device, torch_dtype)
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=settings.models.caption_tokens,
                do_sample=False,
                num_beams=settings.models.caption_beams,
            )
            generated_text = processor.batch_decode(
                generated_ids,
                skip_special_tokens=False,
            )[0]
            parsed = processor.post_process_generation(
                generated_text,
                task=task_prompt,
                image_size=(image.width, image.height),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to describe screenshot {image_path.name} with Florence-2: {exc}"
            ) from exc

        descriptions.append(str(parsed.get(task_prompt, "")).strip())
    return descriptions
