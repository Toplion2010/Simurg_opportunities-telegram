import re


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


class TextCleaner:
    def clean(self, text: str) -> str:
        text = _HTML_TAG_RE.sub("", text)
        text = _MULTI_SPACE_RE.sub(" ", text)
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return text.strip()

    def extract_urls(self, text: str) -> list[str]:
        url_re = re.compile(
            r"https?://[^\s\)\]\>\"\']+",
            re.IGNORECASE,
        )
        return url_re.findall(text)
