"""Group co-spiking terms into events.

A story does not arrive as one word. "harbour", "bridge closed" and
"#trafficchaos" spike together because they are the same thing being said three
ways, and reporting them as three alerts leaves the reader to reassemble the
story by eye.

The method is the one Twitter runs in production and the event-detection
literature settled on: build a graph whose nodes are the terms spiking in a
window and whose edges are how often they appear in the same posts, then take
its communities as events, then chain the communities across windows so an
event has a life rather than a moment.

Nothing here is expensive. The graph spans the terms spiking in one bucket -
dozens at most - not the vocabulary.
"""
from __future__ import annotations

from collections import defaultdict

# Two terms are linked when most of the rarer one's posts also carry the other.
# Overlap rather than Jaccard: "bridge" may be far more common than
# "#trafficchaos" without being any less part of the same story, and Jaccard
# punishes exactly that asymmetry.
MIN_EDGE_WEIGHT = 0.35

# How similar two windows' term sets must be to count as the same event
# continuing rather than a new one starting.
CHAIN_SIMILARITY = 0.3


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def overlap_graph(
    term_posts: dict[str, set[str]], min_weight: float = MIN_EDGE_WEIGHT
) -> dict[str, dict[str, float]]:
    """Weighted adjacency over terms that share the posts they appear in.

    `term_posts` maps each spiking term to the ids of posts carrying it.
    """
    terms = sorted(term_posts)
    graph: dict[str, dict[str, float]] = {t: {} for t in terms}
    for i, left in enumerate(terms):
        posts_left = term_posts[left]
        if not posts_left:
            continue
        for right in terms[i + 1:]:
            posts_right = term_posts[right]
            if not posts_right:
                continue
            shared = len(posts_left & posts_right)
            if not shared:
                continue
            weight = shared / min(len(posts_left), len(posts_right))
            if weight >= min_weight:
                graph[left][right] = weight
                graph[right][left] = weight
    return graph


def louvain(graph: dict[str, dict[str, float]]) -> list[set[str]]:
    """Communities by modularity, via Louvain's local-moving phase.

    Only the first phase: nodes move to whichever neighbouring community gains
    the most modularity, repeatedly, until nothing moves. Louvain's second
    phase aggregates each community into a node and recurses, which matters for
    graphs of millions of nodes and changes nothing on graphs of a few dozen -
    which is all a single bucket of spiking terms ever produces.

    A term with no qualifying edges is its own community, which is correct: it
    spiked alone and is its own event.
    """
    total_weight = sum(sum(edges.values()) for edges in graph.values()) / 2
    if total_weight <= 0:
        return [{node} for node in graph]

    community = {node: node for node in graph}
    degree = {node: sum(edges.values()) for node, edges in graph.items()}
    community_degree = dict(degree)

    improved = True
    while improved:
        improved = False
        for node in graph:
            own = community[node]
            community_degree[own] -= degree[node]

            # Weight from this node into each neighbouring community.
            into: dict[str, float] = defaultdict(float)
            into[own] += 0.0
            for neighbour, weight in graph[node].items():
                into[community[neighbour]] += weight

            best, best_gain = own, 0.0
            base = into[own] - community_degree[own] * degree[node] / (2 * total_weight)
            for candidate, weight in into.items():
                gain = weight - community_degree[candidate] * degree[node] / (2 * total_weight)
                if gain > base and gain > best_gain:
                    best, best_gain = candidate, gain

            community[node] = best
            community_degree[best] += degree[node]
            if best != own:
                improved = True

    grouped: dict[str, set[str]] = defaultdict(set)
    for node, label in community.items():
        grouped[label].add(node)
    return sorted(grouped.values(), key=lambda c: (-len(c), sorted(c)[0]))


def cluster_terms(term_posts: dict[str, set[str]]) -> list[set[str]]:
    """Spiking terms, grouped into the events they belong to."""
    if not term_posts:
        return []
    return louvain(overlap_graph(term_posts))


def event_key(terms: set[str], first_bucket: int) -> str:
    """A stable name for one occurrence of an event.

    The term set alone is not enough. The same story running again next week
    produces the same words, so keying on words alone would silently merge two
    occurrences into one eternal event and destroy the very distinction that
    makes a repeat recognisable. The window it began in makes each occurrence
    its own thing; continuations keep the key they were chained to, so the
    window in the key is always the one the story actually started in.

    Alphabetical order is arbitrary but reproducible, which is what a key
    needs to be.
    """
    return f"{'+'.join(sorted(terms)[:3])}@{first_bucket}"


def chain(
    terms: set[str], recent: list[tuple[str, set[str]]], threshold: float = CHAIN_SIMILARITY
) -> str | None:
    """The key of the open event this cluster continues, if any.

    `recent` is the open events of the preceding windows, newest first, as
    (key, terms). An event's wording drifts as a story develops - new names
    appear, early guesses drop away - so continuation is decided by overlap
    rather than by equality.
    """
    best_key, best_score = None, threshold
    for key, previous in recent:
        score = jaccard(terms, previous)
        if score >= best_score:
            best_key, best_score = key, score
    return best_key
