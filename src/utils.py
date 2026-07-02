import re

_QUOTE_CHARS = '"“”‘’\''

_FEAT_RE = re.compile(r'[ \t](?:featuring|feat\.?|ft\.?)[ \t]', re.IGNORECASE)

# Some Billboard-scraped collab credits are wrapped in literal quote characters,
# e.g. '"HUNTR/X: EJAE, Audrey Nuna & REI AMI"' — strip those before splitting.
def _strip_quotes(s):
    return str(s).strip().strip(_QUOTE_CHARS).strip()


# Band names that contain "/" but are a single act, not a multi-artist credit
# (kworb/Billboard write these with no surrounding spaces, indistinguishable by
# regex from a genuine multi-artist credit like "John Lennon/Plastic Ono Band").
_ATOMIC_ACTS = ["AC/DC", "HUNTR/X"]
_SLASH_PLACEHOLDER = "⁄"  # fraction slash: stands in for "/" inside atomic acts during splitting


def _protect_atomic_acts(s):
    for act in _ATOMIC_ACTS:
        s = re.sub(re.escape(act), lambda m: m.group(0).replace("/", _SLASH_PLACEHOLDER), s, flags=re.IGNORECASE)
    return s


_ALL_SPLIT_RE = re.compile(
    r'\s*,\s*'                              # comma
    r'|\s*&\s*'                             # ampersand
    r'|\s*/\s*'                             # slash (atomic acts protected above)
    r'|\s*:\s*'                             # colon
    r'|\s+x\s+'                             # " x " (space-padded, so "Lil Nas X" is untouched)
    r'|\s+with\s+'
    r'|\s+vs\.?\s+'
    r'|[ \t](?:featuring|feat\.?|ft\.?)[ \t]',
    re.IGNORECASE,
)


def split_artists(artist):
    """
    Split a Billboard-style artist string into (main, featured) parts.

    "The Chainsmokers Featuring Halsey" -> ("The Chainsmokers", "Halsey")
    "Bruno Mars"                         -> ("Bruno Mars", None)
    """
    a = _strip_quotes(artist)
    parts = _FEAT_RE.split(a, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return a, None


def split_all_artists(artist):
    """
    Split a raw artist credit into every individual collaborator.

    Handles "&", ",", " x ", " with ", " vs ", ":", "/" and feat/ft/featuring,
    e.g. "Anuel AA, Daddy Yankee, Karol G, Ozuna & J Balvin" ->
    ["Anuel AA", "Daddy Yankee", "Karol G", "Ozuna", "J Balvin"].
    """
    s = _protect_atomic_acts(_strip_quotes(artist))
    parts = [_strip_quotes(p).replace(_SLASH_PLACEHOLDER, "/") for p in _ALL_SPLIT_RE.split(s)]
    return [p for p in parts if p]


def artist_csv(artist):
    """Semicolon-separated list of all artists for CSV output."""
    return ";".join(split_all_artists(artist))


def artist_html(artist):
    """HTML artist cell: featured names in a muted span."""
    main, feat = split_artists(artist)
    if feat:
        return f'{main} <span class="feat">feat. {feat}</span>'
    return main
