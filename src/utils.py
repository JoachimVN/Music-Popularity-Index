import re

_QUOTE_CHARS = '"“”‘’\''

_FEAT_RE = re.compile(r'[ \t](?:featuring|feat\.?|ft\.?)[ \t]', re.IGNORECASE)

# Some Billboard-scraped collab credits are wrapped in literal quote characters,
# e.g. '"HUNTR/X: EJAE, Audrey Nuna & REI AMI"' — strip those before splitting.
def _strip_quotes(s):
    return str(s).strip().strip(_QUOTE_CHARS).strip()


# Artist names that contain a separator used by multi-artist credits. These need
# an explicit list: punctuation alone cannot distinguish a band such as "Nico &
# Vinz" from a genuine collaboration such as "Lady Gaga & Bruno Mars".
_ATOMIC_ACTS = [
    "AC/DC",
    "HUNTR/X",
    "Nico & Vinz",
    "Earth, Wind & Fire",
    "Tyler, The Creator",
    "Lil Nas X",
    "Silk Sonic (Bruno Mars & Anderson .Paak)",
    "The Mamas & The Papas",
    "Dan + Shay",
    "Sly & The Family Stone",
    "C+C Music Factory",
    "Kool & The Gang",
    "Simon & Garfunkel",
    "Mumford & Sons",
    "Florence + The Machine",
    "Captain & Tennille",
    "The Captain & Tennille",
    "D.J. Jazzy Jeff & The Fresh Prince",
    "Lipps, Inc.",
    "Sonny & Cher",
    "Peaches & Herb",
    "Sam & Dave",
    "England Dan & John Ford Coley",
    "Booker T. & The MG's",
    "Michael Franti & Spearhead",
    "K-Ci & JoJo",
    # Additional high-confidence group and duo names found in the full export.
    "10,000 Maniacs",
    "Alex & Sierra",
    "Alina Baraz & Galimatias",
    "Aly & AJ",
    "Angels & Airwaves",
    "Angus & Julia Stone",
    "Artists Of Then, Now & Forever",
    "Ashford & Simpson",
    "Ashton, Gardner & Dyke",
    "Ayo & Teo",
    "Big & Rich",
    "Blood, Sweat & Tears",
    "Booker T. & The M.G.'s",
    "Crosby, Stills & Nash",
    "Crosby, Stills, Nash & Young",
    "Dave Dee, Dozy, Beaky, Mick And Tich",
    "Dino, Desi & Billy",
    "Emerson, Lake & Palmer",
    "Emerson, Lake & Powell",
    "for KING & COUNTRY",
    "Hagar, Schon, Aaronson, Shrieve",
    "Hamilton, Joe Frank & Dennison",
    "Hamilton, Joe Frank & Reynolds",
    "Hodges, James And Smith",
    "Hootie & The Blowfish",
    "Isley, Jasper, Isley",
    "Macklemore & Ryan Lewis",
    "McGuinn, Clark & Hillman",
    "Of Monsters & Men",
    "Peter, Paul & Mary",
    "Ray Parker Jr. & Raydio",
    "Ray, Goodman & Brown",
    "Rene & Rene",
    "RKM & Ken-Y",
    "Rob Base & D.J. E-Z Rock",
    "Rodney O & Joe Cooley",
    "Seals & Crofts",
    "She & Him",
    "Shirley & Lee",
    "Siouxsie & The Banshees",
    "SOB X RBE",
    "Tanto Metro & Devonte",
    "The Lewis & Clarke Expedition",
    "The Naked & Famous",
    "The Souther, Hillman, Furay Band",
    "The Swell Season (Glen Hansard & Marketa Irglova)",
    "Tom Petty & The Heartbreakers",
    "Tommy Boyce & Bobby Hart",
    "Tommy James & The Shondells",
    "TOMORROW X TOGETHER",
    "Tony Orlando & Dawn",
    "Vigrass & Osborne",
    "Vremya & Steklo",
    "Wisin & Yandel",
    "Yandar & Yostin",
    "Yarbrough & Peoples",
    "Young T & Bugsey",
    "Zager & Evans",
    "Zion & Lennox",
    "Zé Neto & Cristiano",
]
_SEPARATOR_PLACEHOLDERS = {
    "/": "⁄",
    "&": "﹠",
    ",": "﹐",
    "+": "﹢",
    "x": "ｘ",
    "X": "Ｘ",
}


def _protect_atomic_acts(s):
    for act in _ATOMIC_ACTS:
        s = re.sub(
            re.escape(act),
            lambda m: m.group(0).translate(str.maketrans(_SEPARATOR_PLACEHOLDERS)),
            s,
            flags=re.IGNORECASE,
        )
    return s


def _restore_atomic_separators(s):
    return s.translate(str.maketrans({value: key for key, value in _SEPARATOR_PLACEHOLDERS.items()}))


_ALL_SPLIT_RE = re.compile(
    r'\s*,(?!\s*(?:Jr\.?|Sr\.?|I{1,4}|V)\b)\s*'  # comma, except name suffixes
    r'|\s*&\s*'                             # ampersand
    r'|\s*\+\s*'                            # plus, e.g. "Jay-Z + Alicia Keys"
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

    Handles "&", "+", ",", " x ", " with ", " vs ", ":", "/" and feat/ft/featuring,
    e.g. "Anuel AA, Daddy Yankee, Karol G, Ozuna & J Balvin" ->
    ["Anuel AA", "Daddy Yankee", "Karol G", "Ozuna", "J Balvin"].
    """
    s = _protect_atomic_acts(_strip_quotes(artist))
    parts = [_restore_atomic_separators(_strip_quotes(p)) for p in _ALL_SPLIT_RE.split(s)]
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
