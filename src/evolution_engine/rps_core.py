"""Adapted from frozen Experiment 8 engine.py; see ARCHITECTURE.md provenance.

Moves are 1=rock, 2=paper, 3=scissors. Histories are oldest to newest;
the Scratch input vector one-hot encodes newest, middle, oldest in that order.
"""
from __future__ import annotations

import itertools
import math
import numpy as np

HISTORIES = [(0, 0, 0)] + [(0, 0, x) for x in (1, 2, 3)] + [
    (0, x, y) for x in (1, 2, 3) for y in (1, 2, 3)
] + list(itertools.product((1, 2, 3), repeat=3))
assert len(HISTORIES) == 40
HINDEX = {h: i for i, h in enumerate(HISTORIES)}
INPUTS = np.array(
    [[float(m == v) for m in (h[2], h[1], h[0]) for v in (1, 2, 3)] for h in HISTORIES],
    dtype=np.float64,
)
NEXT = np.array([[HINDEX[(h[1], h[2], m)] for m in (1, 2, 3)] for h in HISTORIES], dtype=np.uint8)
FULL = np.array([HINDEX[h] for h in HISTORIES if all(h)], dtype=np.uint8)


def scratch_outputs(genes, history):
    """Independent scalar translation of the Scratch neuron's accumulation order."""
    if len(genes) != 159 or tuple(history) not in HINDEX:
        raise ValueError("expected 159 parameters and one reachable history")
    x = [float(m == v) for m in history[::-1] for v in (1, 2, 3)]
    hidden = []
    for neuron in range(12):
        total = x[0] * genes[neuron * 9]
        for j in range(1, 9):
            total += x[j] * genes[neuron * 9 + j]
        u = total + genes[144 + neuron]
        hidden.append(1 / (1 + math.exp(-u)) if u >= 0 else math.exp(u) / (1 + math.exp(u)))
    out = []
    for neuron in range(3):
        total = hidden[0] * genes[108 + neuron * 12]
        for j in range(1, 12):
            total += hidden[j] * genes[108 + neuron * 12 + j]
        out.append(total + genes[156 + neuron])
    return out


def scratch_move(genes, history):
    out = scratch_outputs(genes, history)
    best, idx = -1000.0, -1000
    for i, value in enumerate(out, 1):
        if value > best:
            best, idx = value, i
    return idx


def policies(genes):
    """Vectorized 40-history lookup; input is (N,159) float64."""
    g = np.asarray(genes, dtype=np.float64)
    if g.ndim == 1:
        g = g[None, :]
    if g.ndim != 2 or g.shape[1] != 159:
        raise ValueError("expected N by 159 parameters")
    h = np.einsum("si,nhi->nsh", INPUTS, g[:, :108].reshape(-1, 12, 9), optimize=True)
    h += g[:, None, 144:156]
    h = 1 / (1 + np.exp(-np.clip(h, -700, 700)))
    o = np.einsum("nsh,nch->nsc", h, g[:, 108:144].reshape(-1, 3, 12), optimize=True)
    o += g[:, None, 156:159]
    # Scratch starts at -1000 and uses strict greater-than; normal genomes have
    # output values well above this. Verify that bound in the index stage.
    return (np.argmax(o, axis=2) + 1).astype(np.uint8), o


def score(a, b):
    return (int(a) - int(b) + 1) % 3 - 1


def match(policy_a, policy_b, length=23, history_a=(0, 0, 0), history_b=(0, 0, 0)):
    """Play simultaneous throws; history_a/b contain each player's own moves."""
    ha, hb = HINDEX[tuple(history_a)], HINDEX[tuple(history_b)]
    net = wins = losses = draws = 0
    for _ in range(length):
        a, b = int(policy_a[hb]), int(policy_b[ha])
        s = score(a, b)
        net += s
        wins += s > 0
        losses += s < 0
        draws += s == 0
        ha, hb = int(NEXT[ha, a - 1]), int(NEXT[hb, b - 1])
    return net, wins, losses, draws


def batch_matches(pa, pb, length=23, start=(0, 0, 0)):
    """All ordered pairs of policies in arrays pa and pb, using NumPy states."""
    pa, pb = np.asarray(pa, dtype=np.uint8), np.asarray(pb, dtype=np.uint8)
    na, nb = len(pa), len(pb)
    shape = (na, nb)
    ha = np.full(shape, HINDEX[tuple(start)], dtype=np.uint8)
    hb = ha.copy()
    net = np.zeros(shape, dtype=np.int64)
    wins = np.zeros(shape, dtype=np.int64)
    losses = np.zeros(shape, dtype=np.int64)
    draws = np.zeros(shape, dtype=np.int64)
    ai = np.arange(na)[:, None]
    bi = np.arange(nb)[None, :]
    for _ in range(length):
        a, b = pa[ai, hb], pb[bi, ha]
        s = ((a.astype(np.int16) - b.astype(np.int16) + 1) % 3 - 1)
        net += s
        wins += s > 0
        losses += s < 0
        draws += s == 0
        ha, hb = NEXT[ha, a - 1], NEXT[hb, b - 1]
    return net, wins, losses, draws


def original_bot_moves(kind, offset, length=20):
    moves = []
    for t in range(1, length + 1):
        v = (t + offset - 1) % 3
        moves.append((v + 1, (2 * v) % 3 + 1, 1 + int(v == 2))[kind - 1])
    return moves


def original_bot_score(policy, kind, offset, length=20):
    hb, total = HINDEX[(0, 0, 0)], 0
    for bot_move in original_bot_moves(kind, offset, length):
        total += score(policy[hb], bot_move)
        hb = int(NEXT[hb, bot_move - 1])
    return total
