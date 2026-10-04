from __future__ import annotations

import hashlib
import random

from .common import PROTOCOL, Op

PER_BATCH = 100
QUERIES = 24

# Grammatical filler on purpose: random word salad has been refused by the API as gibberish.
ADJECTIVES = (
    "amber quiet narrow distant gentle hollow bright ancient restless silver patient crooked "
    "frozen golden humble jagged mellow nimble pale rugged sturdy tender vivid weary"
).split()
NOUNS = (
    "river lantern orchard harbor meadow glacier valley bridge compass anchor garden kettle "
    "ladder mirror needle pebble quarry ribbon saddle thimble tunnel vessel window willow"
).split()
VERBS = (
    "carries follows guards mends crosses shelters lifts answers gathers borrows measures "
    "paints signals trusts watches welcomes"
).split()

TASK = (
    "You are a key-value store.\n\n"
    + PROTOCOL
    + "\nSET operations give you values to remember; each value is 24 words followed by a "
    "#tag. GET operations ask for one key. Answer a GET with the id set to the key and the "
    "value copied exactly, tag included."
)


def _value(rng: random.Random, seed: int, key: str) -> str:
    clauses = [
        f"the {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)} {rng.choice(VERBS)} "
        f"the {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        for _ in range(3)
    ]  # 3 clauses x 7 words, plus a 3-word tail = 24 words
    clauses.append(f"near the {rng.choice(NOUNS)}")
    tag = hashlib.sha1(f"{seed}:{key}".encode()).hexdigest()[:8]
    return f"{' '.join(clauses)} #{tag}"


def generate(seed: int, batches: int) -> list[Op]:
    rng = random.Random(seed)
    ops: list[Op] = []
    values: dict[str, str] = {}
    for b in range(batches):
        lines = [f"<<<SET-BATCH {b:04d} BEGIN>>>"]
        for i in range(PER_BATCH):
            key = f"K{b * PER_BATCH + i:05d}"
            values[key] = _value(rng, seed, key)
            lines.append(f"SET {key} = {values[key]}")
        lines.append(f"<<<SET-BATCH {b:04d} END>>>")
        ops.append(Op("\n".join(lines)))
    for key in rng.sample(sorted(values), min(QUERIES, len(values))):
        ops.append(Op(f"GET {key}", answer_id=key, answer=values[key]))
    return ops
