"""Use the existing exact-source contract without rendering any media."""
from immich_memories.analysis.theme_discovery import ThemeCandidate, ThemeResult
from immich_memories.store.theme_captions import ThemeCaption


def build_handoff(library, key, title, brief, interpretation, decisions):
    """Export explicit matches only and preserve the full original brief."""
    if any(type(i) is not int or not 0 <= i < len(library.rows) for i in decisions):
        raise ValueError('Unknown source reference')
    if any(d not in {'match','reject','unknown'} for d in decisions.values()):
        raise ValueError('Unknown source decision')
    selected = sorted((i for i,d in decisions.items() if d == 'match'),
                      key=lambda i:library.rows[i]['taken_at'])
    evidence = tuple(ThemeCaption(**{k:library.rows[i][k] for k in
                    ('asset_id','taken_at','caption','media_kind')},
                    place=library.rows[i].get('city','')) for i in selected)
    candidates = (ThemeCandidate(key=key,title=title,brief=brief,
                  interpretation=interpretation,evidence=evidence),) if evidence else ()
    return ThemeResult(total_assets=getattr(library,'total_assets',len(library.rows)),
                       captioned_assets=len(library.rows),reviewed_assets=len(decisions),
                       candidates=candidates)
