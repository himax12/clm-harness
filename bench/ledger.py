from __future__ import annotations

import random

from .common import PROTOCOL, Op

ACCOUNTS = 120
PER_BATCH = 200
QUERY_EVERY = 3  # one balance query after every third batch

TASK = (
    "You keep a ledger of account balances.\n\n"
    + PROTOCOL
    + "\nThe first operation opens the accounts with their starting balances. Later "
    "operations are batches of transfers: `TRANSFER A017 -> A093 : 412` moves 412 from A017 "
    "to A093. Balances may go negative. A QUERY asks for one account's current balance; "
    "answer with the id set to the query id (for example q07) and the balance as a plain integer."
)


def generate(seed: int, batches: int) -> list[Op]:
    rng = random.Random(seed)
    names = [f"A{i:03d}" for i in range(ACCOUNTS)]
    balance = {name: rng.randint(1_000, 9_999) for name in names}
    ops = [Op("\n".join(["<<<OPEN ACCOUNTS>>>", *(f"OPEN {n} = {balance[n]}" for n in names),
                         "<<<OPEN END>>>"]))]
    query = 0
    for b in range(batches):
        lines = [f"<<<TRANSFERS {b:04d} BEGIN>>>"]
        for _ in range(PER_BATCH):
            src, dst = rng.sample(names, 2)
            amount = rng.randint(1, 500)
            balance[src] -= amount
            balance[dst] += amount
            lines.append(f"TRANSFER {src} -> {dst} : {amount}")
        lines.append(f"<<<TRANSFERS {b:04d} END>>>")
        ops.append(Op("\n".join(lines)))
        if (b + 1) % QUERY_EVERY == 0:
            query += 1
            name = rng.choice(names)
            ops.append(Op(f"QUERY q{query:02d}: what is the current balance of {name}?",
                          answer_id=f"q{query:02d}", answer=str(balance[name])))
    return ops
