"""Shared formatting for Clash player and clan tags.

Validation and storage-key conventions remain with each feature's owner.
"""


def normalize(tag: object) -> str:
    """Strip surrounding whitespace, uppercase, correct O to 0 and add #.

    Empty input stays empty so callers can retain their existing missing-value
    validation. This formatter does not validate the Clash alphabet or length.
    """
    value = str(tag or "").strip().upper().replace("O", "0")
    if value and not value.startswith("#"):
        value = "#" + value
    return value
