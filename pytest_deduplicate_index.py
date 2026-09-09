"""Exact interned arc sets with an inverted index; no similarity heuristics."""


class ArcIndex:
    def __init__(self, coverages):
        identities = {}
        self.rows, self.postings = [], {}
        for index, coverage in enumerate(coverages):
            row = set()
            for file, arcs in coverage.file_arcs.items():
                for arc in arcs:
                    identity = (file, *arc)
                    code = identities.setdefault(identity, len(identities))
                    row.add(code)
                    self.postings.setdefault(code, set()).add(index)
            self.rows.append(frozenset(row))

    def containment_pairs(self):
        for left, row in enumerate(self.rows):
            if not row:
                continue
            candidates = min((self.postings[arc] for arc in row), key=len)
            for right in sorted(candidates):
                if left != right and row <= self.rows[right]:
                    yield left, right

    def overlapping_smaller(self, index):
        row = self.rows[index]
        candidates = set()
        for arc in row:
            candidates.update(self.postings[arc])
        return sorted(i for i in candidates if i > index and len(self.rows[i]) < len(row))
