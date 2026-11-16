"""编码回退链。

优先按 BOM 判断；无 BOM 时严格 UTF-8 先试，失败再回退 gb18030 / big5。
回退不是静默的：调用方拿得到真正生效的编码，页面与清单都会显示。
"""

from __future__ import annotations

from dataclasses import dataclass

from app import config

BOM_UTF8 = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class Decoded:
    text: str
    encoding: str
    bom: bool
    attempts: tuple[str, ...]


def _try(raw: bytes, encoding: str) -> str | None:
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


def decode_bytes(raw: bytes) -> Decoded:
    if raw is None or raw.strip() == b"":
        raise ValueError("empty")

    attempts: list[str] = []
    if raw.startswith(BOM_UTF8):
        attempts.append("utf-8-sig")
        text = _try(raw, "utf-8-sig")
        if text is not None:
            return Decoded(text=text, encoding="utf-8-sig", bom=True, attempts=tuple(attempts))

    for encoding in config.ENCODINGS:
        if encoding == "utf-8-sig":
            continue
        attempts.append(encoding)
        text = _try(raw, encoding)
        if text is None:
            continue
        clean = text.lstrip("\ufeff")
        return Decoded(
            text=clean,
            encoding=encoding,
            bom=text.startswith("\ufeff"),
            attempts=tuple(attempts),
        )

    raise ValueError("undecodable")
