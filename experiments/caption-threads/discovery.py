"""Caption-only retrieval and evidence sampling for the private prototype."""
import math
import re
from collections import Counter, defaultdict


GLUE = set("a an the and or but with without of in on at by to for from into onto over under near next while as is are was were be been being has have had do does did this that these those it its their his her our your my image photo photograph picture scene view background foreground closeup someone something thing seen shown shows showing appears appearing appear featuring features feature there here".split())


def words(text):
    return set(re.findall(r"[^\W\d_]{3,}", text.casefold())) - GLUE


class Library:
    """Keep retrieval refs tied to immutable original captions."""

    def __init__(self, rows):
        self.rows = rows
        self.tokens = [words(r["caption"]) for r in rows]
        self.posts = defaultdict(set)
        for i, tokens in enumerate(self.tokens):
            for token in tokens:
                self.posts[token].add(i)

    def facts(self, refs):
        refs = sorted(set(refs))
        dates = {self.rows[i]["taken_at"][:10] for i in refs}
        return {"refs": refs, "captions": len(refs), "days": len(dates),
                "years": dict(sorted(Counter(d[:4] for d in dates).items())),
                "span": [min(dates), max(dates)] if dates else [],
                "countries": sorted({self.rows[i].get("country", "") for i in refs} - {""})}

    def recurrences(self, min_days=4, min_years=3):
        """Nominate recurrence without giving burst size a temporal vote."""
        result = []
        for anchor, refs in self.posts.items():
            facts = self.facts(refs)
            if facts["days"] >= min_days and len(facts["years"]) >= min_years:
                result.append({"anchor": anchor, **facts})
        return result

    def witnesses(self, refs, limit=16):
        """Spread actual sources across years and places, one source per day."""
        remaining = set(refs)
        years = Counter()
        places = Counter()
        selected = []
        dates = set()
        while remaining and len(selected) < limit:
            def score(i):
                row = self.rows[i]
                year = row["taken_at"][:4]
                place = (row.get("country", ""), row.get("region", row.get("city", "")))
                return (1 / (1 + years[year]) + .65 / (1 + places[place]),
                        len(self.tokens[i]), -i)
            i = max(remaining, key=score)
            row = self.rows[i]
            date = row["taken_at"][:10]
            selected.append(i)
            years[date[:4]] += 1
            places[(row.get("country", ""), row.get("region", row.get("city", "")))] += 1
            dates.add(date)
            remaining = {j for j in remaining if self.rows[j]["taken_at"][:10] not in dates}
        return [self.source(i) for i in sorted(selected, key=lambda i: self.rows[i]["taken_at"])]

    def source(self, ref):
        row = self.rows[ref]
        return {"ref": ref, "asset_id": row["asset_id"], "date": row["taken_at"][:10],
                "caption": row["caption"], "media_kind": row.get("media_kind", "photo"),
                "city": row.get("city", ""), "country": row.get("country", ""),
                "region": row.get("region", ""),
                "co_present_people": row.get("person_refs", [])}

    def geographic_candidates(self):
        """Infer geographic contrast from recorded dates, not a travel keyword."""
        country_days = defaultdict(set)
        year_country_days = defaultdict(lambda: defaultdict(set))
        by_country = defaultdict(list)
        for i, row in enumerate(self.rows):
            country = row.get("country")
            if not country:
                continue
            day = row["taken_at"][:10]
            country_days[country].add(day)
            year_country_days[day[:4]][country].add(day)
            by_country[country].append(i)
        if len(country_days) < 2:
            return []
        base = max(country_days, key=lambda c: len(country_days[c]))
        annual_bases = {y: max(cs, key=lambda c: len(cs[c]))
                        for y, cs in year_country_days.items()}
        refs = [i for i, row in enumerate(self.rows) if row.get("country")
                and row["country"] != annual_bases[row["taken_at"][:4]]]
        result = []
        facts = self.facts(refs)
        if facts["days"] >= 4 and len(facts["years"]) >= 3:
            result.append({"key": "geo:contrast", "anchor": "changing geographic settings",
                           "operator": "geographic_variation", "base_country": base,
                           "annual_bases": annual_bases,
                           "claim": "Pictures in different countries across years; test travel context",
                           **facts})
        for country, refs in by_country.items():
            facts = self.facts(refs)
            if country != base and facts["days"] >= 4 and len(facts["years"]) >= 3:
                result.append({"key": "geo:" + country, "anchor": country,
                               "operator": "returning_geography", "base_country": base,
                               "claim": "Recurring recorded location across years; test visits and returns",
                               **facts})
        return result

    def connections(self, anchors, max_days=40):
        """Keep rare caption terms that actually touch more than one subject."""
        anchors = {k: set(v) for k, v in anchors.items()}
        result = []
        for term, refs in self.posts.items():
            if term in anchors:
                continue
            days = {self.rows[i]["taken_at"][:10] for i in refs}
            if len(days) > max_days:
                continue
            touched = {k: sorted(refs & members) for k, members in anchors.items() if refs & members}
            if len(touched) < 2:
                continue
            # A connector shared by nearly everything is context, not a useful edge.
            if len(touched) > max(6, len(anchors) // 3):
                continue
            witness_refs = sorted(set().union(*(set(v) for v in touched.values())))
            result.append({"connector": term, "anchors": sorted(touched),
                           "witness_refs": witness_refs, "anchor_refs": touched,
                           "days": len(days), "status": "hypothesis",
                           "score": round(math.log1p(len(touched)) / math.sqrt(len(days)), 4)})
        return sorted(result, key=lambda c: (-c["score"], c["connector"]))

    def context(self, refs):
        """Expose changes without treating co-presence as identity or ownership."""
        refs = set(refs)
        by_year = defaultdict(list)
        by_place = defaultdict(list)
        term_days = defaultdict(set)
        for i in refs:
            row = self.rows[i]
            by_year[row["taken_at"][:4]].append(i)
            by_place[(row.get("country", ""), row.get("region", row.get("city", "")))].append(i)
            for term in self.tokens[i]:
                term_days[term].add(row["taken_at"][:10])
        def related(year_refs):
            counts = Counter(t for i in year_refs for t in self.tokens[i])
            return [t for t, _ in sorted(counts.items(), key=lambda kv:
                    -kv[1] / math.sqrt(len(self.posts[kv[0]])))[:8]]
        years = sorted(by_year)
        eras = [years[:max(1, len(years)//3)], years[max(1, len(years)//3):max(2, 2*len(years)//3)],
                years[max(2, 2*len(years)//3):]]
        return {"places": [{"country": country, "region": place,
                            **{k:v for k,v in self.facts(rs).items() if k != "refs"}}
                           for (country, place), rs in sorted(by_place.items(), key=lambda x: -len(x[1]))[:8]],
                "eras": [{"years": era, "associated_words": related([i for y in era for i in by_year[y]])}
                         for era in eras if era],
                "identity": "unresolved: dates, descriptors and co-presence are contextual evidence only"}
