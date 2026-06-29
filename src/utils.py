import re

_FEAT_RE = re.compile(r'[ \t]+(?:featuring|feat\.?|ft\.?)[ \t]+', re.IGNORECASE)


def split_artists(artist):
    """
    Split a Billboard-style artist string into (main, featured) parts.

    "The Chainsmokers Featuring Halsey" -> ("The Chainsmokers", "Halsey")
    "Bruno Mars"                         -> ("Bruno Mars", None)
    """
    parts = _FEAT_RE.split(artist, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return artist.strip(), None


def artist_csv(artist):
    """Semicolon-separated artist string for CSV output."""
    main, feat = split_artists(artist)
    return f"{main};{feat}" if feat else main


def artist_html(artist):
    """HTML artist cell: featured names in a muted span."""
    main, feat = split_artists(artist)
    if feat:
        return f'{main} <span class="feat">feat. {feat}</span>'
    return main
