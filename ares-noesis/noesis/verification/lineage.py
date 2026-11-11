"""Evidence lineage: papers sharing an author are one lineage and count once in belief pooling.

Replaces the first-author-surname proxy (which treated two papers by the same group as independent whenever the first author differed).
Rule: two papers share a lineage if they share any author, matched on (first initial, surname). This is deliberately conservative:
common names will over-merge, which understates independence rather than overstating it. Papers with no author data fall back to their own DOI/id."""
import re


def _key(name: str):
    parts = re.sub(r"[^\w\s]", " ", (name or "").lower()).split()
    if len(parts) < 2:
        return None                      # a bare surname is too ambiguous to link on
    return f"{parts[0][0]} {parts[-1]}"


def lineage_groups(items: dict) -> dict:
    """items: {paper_key: [author names]} -> {paper_key: group label}."""
    parent = {k: k for k in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    seen = {}
    for k, authors in items.items():
        for a in authors or []:
            ak = _key(a)
            if ak is None:
                continue
            if ak in seen:
                parent[find(k)] = find(seen[ak])
            else:
                seen[ak] = k
    comp = {}
    for k in items:
        comp.setdefault(find(k), []).append(k)
    label = {r: min(ms) for r, ms in comp.items()}          # stable label: smallest member key
    return {k: f"lineage:{label[find(k)]}" for k in items}
