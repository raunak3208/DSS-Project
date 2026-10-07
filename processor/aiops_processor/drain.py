"""Drain-lite log parser: mask variables, group by (level, length, first token), merge similar lines into templates."""
import re

MASKS = [(re.compile(r"\b[0-9a-f]{8,}\b"), "<*>"),
         (re.compile(r"\b\d+(\.\d+)?ms\b"), "<*>ms"),
         (re.compile(r"\b\d+(\.\d+)?\b"), "<*>")]


def tokenize(level, msg):
    for rx, rep in MASKS:
        msg = rx.sub(rep, msg)
    return [level] + msg.split()


class Drain:
    def __init__(self, sim=0.6, max_clusters=1000):
        self.groups, self.sim, self.n, self.max = {}, sim, 0, max_clusters

    def add(self, level, msg):
        """Returns (template_id, template_text, is_new)."""
        toks = tokenize(level, msg)
        group = self.groups.setdefault((len(toks), toks[0], toks[1] if len(toks) > 1 else ""), [])
        best, best_sim = None, 0.0
        for c in group:
            s = sum(a == b or a == "<*>" for a, b in zip(c["t"], toks)) / len(toks)
            if s > best_sim:
                best, best_sim = c, s
        if best and best_sim >= self.sim:
            best["t"] = [a if a == b else "<*>" for a, b in zip(best["t"], toks)]
            best["count"] += 1
            return best["id"], " ".join(best["t"][1:]), False
        self.n += 1
        c = {"id": self.n, "t": toks, "count": 1}
        group.append(c)
        return c["id"], " ".join(toks[1:]), True
