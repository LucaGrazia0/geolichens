"""Shared conservative name variants; keep the original specimen text intact."""
import re
import unicodedata
from difflib import SequenceMatcher


def normalize_name(value):
    text = str(value or '').replace('’', "'").replace('`', "'")
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text.replace(',', ' ')).strip()


def name_variants(value):
    original = re.sub(r'\s+', ' ', str(value or '').strip()).replace('’', "'").replace('`', "'")
    expanded = original
    for pattern, word in ((r'\b(?:m\.te|mt\.)\s*', 'Monte '),
                          (r'\brif\.\s*', 'Rifugio '),
                          (r'\bp\.so\s*', 'Passo '),
                          (r'\bl\.to\s*', 'Laghetto ')):
        expanded = re.sub(pattern, word, expanded, flags=re.IGNORECASE)
    variants = [original, expanded]
    folded = unicodedata.normalize('NFKD', expanded)
    variants.append(''.join(c for c in folded if not unicodedata.combining(c)))
    return list(dict.fromkeys(v.strip() for v in variants if v.strip()))


def locality_kind(value):
    text = normalize_name(name_variants(value)[-1]) if str(value or '').strip() else ''
    for kind, pattern in (
        ('pass', r'\b(passo|forcella|sella|bocchetta)\b'),
        ('summit_peak', r'\b(cima|vetta|pizzo|punta|corno)\b'),
        ('mountain_area', r'\b(monte|montagna|colle|dosso|poggio)\b'),
        ('valley', r'\b(valle|val)\b'),
        ('hydro', r'\b(lago|laghetto|laghetti|torrente|rio|fiume)\b'),
        ('forest_area', r'\b(bosco|foresta|selva)\b'),
        ('refuge_malga', r'\b(rifugio|bivacco|malga|baita)\b'),
    ):
        if re.search(pattern, text):
            return kind
    return 'locality'


def distinctive_tokens(query, municipality=None):
    variants = name_variants(query)
    normalized = normalize_name(variants[-1]) if variants else ''
    stop = set(('monte montagna cima vetta pizzo punta corno colle dosso poggio passo forcella '
                'sella bocchetta valle val lago laghetto laghetti laghi rifugio bivacco malga baita '
                'bosco foresta selva di del della delle degli dei d dell al alla alle il la lo i le Italia').lower().split())
    # An address context is not the locality's own name: "Braone" alone
    # cannot match "Foppe di Braone" when Braone is the known municipality.
    town_tokens = set(re.findall(r"[\w]+", normalize_name(municipality))) - {'comune', 'di'}
    tokens = [t for t in re.findall(r"[\w]+", normalized)
              if len(t) > 2 and t not in stop and t not in town_tokens and not t.isdigit()]
    return tokens


def name_evidence(query, candidate_name, municipality=None):
    """Separate exact own-name agreement from partial token/typo evidence."""
    variants = name_variants(query)
    expected = normalize_name(variants[-1]) if variants else ''
    names = re.findall(r"[\w]+", normalize_name(candidate_name))
    tokens = distinctive_tokens(query, municipality)
    matches = [max((SequenceMatcher(None, token, name).ratio() for name in names), default=0)
               for token in tokens]
    coverage = sum(v >= .75 for v in matches) / len(matches) if matches else 0.0
    exact = sum(v == 1 for v in matches) / len(matches) if matches else 0.0
    tier = (3 if expected and expected == normalize_name(candidate_name) else
            2 if matches and exact == 1 else 1 if matches and coverage == 1 else 0)
    return tier, coverage


def plausible_name(query, candidate_name, municipality=None):
    """Discard unrelated fuzzy hits, retaining distinctive names and typos."""
    tokens = distinctive_tokens(query, municipality)
    if not tokens:
        return True
    return name_evidence(query, candidate_name, municipality)[1] > 0


def search_variants(value, municipality=None):
    """Search-only simplifications; never rewrite the semantic record or aliases."""
    variants = name_variants(value)
    if not variants:
        return []
    expanded = variants[-1]
    # Joining words are useful in descriptions but may dilute a name search.
    compact = re.sub(r"\b(di|del|della|delle|degli|dei|dell)\b[' ]*", ' ', expanded, flags=re.I)
    compact = re.sub(r'\s+', ' ', compact).strip()
    town = normalize_name(municipality)
    town = re.sub(r'^comune\s+di\s+', '', town)
    core = expanded
    if town:
        normalized = normalize_name(expanded)
        # Remove only a complete municipality suffix, not homonymous substrings
        # inside the toponym. All candidates are still checked on the full name.
        match = re.search(r'(?:\s+(?:di|del|della))?\s+' + re.escape(town) + r'$', normalized)
        if match and normalized[:match.start()].strip():
            core = normalized[:match.start()].strip()
    plan = [*variants, compact, core]
    if municipality and core != expanded:
        plan.append(f'{core}, {municipality}')
    elif municipality:
        plan.append(f'{expanded}, {municipality}')
    plan.append(f'{expanded}, Italia')
    seen = set()
    result = []
    for query in plan:
        key = normalize_name(query)
        if key and key not in seen:
            seen.add(key)
            result.append(query)
    return result
