"""Caption text normalization used by initial analysis and enrichment."""


def normalize_caption(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    if text.lower().startswith("a "):
        text = text[2:]
    elif text.lower().startswith("an "):
        text = text[3:]
    elif text.lower().startswith("the "):
        text = text[4:]
    return text[:1].upper() + text[1:]
