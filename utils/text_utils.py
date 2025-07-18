import re
import unicodedata


def sanitize_filename(text: str) -> str:
    """
    Convert a text string into a safe filename by removing special characters
    and replacing spaces with underscores.

    This function handles:
    - Unicode characters (converts to ASCII equivalents where possible)
    - Special characters (removes them)
    - Spaces (converts to underscores)
    - Multiple underscores (reduces to single)
    - Leading/trailing underscores (removes them)

    Args:
        text: The text to sanitize (e.g., "Arcane Angels!")

    Returns:
        A clean filename-safe string (e.g., "Arcane_Angels")
    """
    # Step 1: Handle Unicode characters
    # This converts characters like é to e, ñ to n, etc.
    # NFD = Canonical Decomposition - separates base characters from accents
    nfd_form = unicodedata.normalize('NFD', text)
    # Keep only ASCII characters
    ascii_text = nfd_form.encode('ASCII', 'ignore').decode('ASCII')

    # Step 2: Replace spaces with underscores
    # This ensures "Arcane Angels" becomes "Arcane_Angels"
    with_underscores = ascii_text.replace(' ', '_')

    # Step 3: Remove any character that isn't alphanumeric or underscore
    # This regex keeps only letters (a-z, A-Z), numbers (0-9), and underscores
    clean_text = re.sub(r'[^a-zA-Z0-9_]', '', with_underscores)

    # Step 4: Clean up multiple underscores
    # This prevents "Arcane___Angels" from bad input
    single_underscores = re.sub(r'_+', '_', clean_text)

    # Step 5: Remove leading/trailing underscores
    # This ensures we don't get "_ArcaneAngels_"
    final_text = single_underscores.strip('_')

    # Step 6: Handle edge case of empty result
    # If everything was stripped out, provide a fallback
    if not final_text:
        return "unnamed"

    return final_text