"""Causal unfamiliar opponents adapted from frozen Experiment 8 generalization.py."""
import random
from .rps_core import HINDEX,NEXT,score

OPPONENTS=("uniform","copycat","anti_copycat","frequency","transition","noisy_cycle","reactive")

def counter(move):
    return move % 3 + 1

def bot_move(kind, t, net_history, bot_history, outcomes, rng):
    if kind == "uniform":
        return rng.randrange(1, 4)
    if kind == "copycat":
        return net_history[-1] if net_history else 1
    if kind == "anti_copycat":
        return counter(net_history[-1]) if net_history else 2
    if kind == "frequency":
        window = net_history[-20:]
        counts = [window.count(i) for i in (1, 2, 3)]
        return counter(counts.index(max(counts)) + 1)
    if kind == "transition":
        previous = net_history[-1] if net_history else 1
        following = [net_history[i + 1] for i in range(len(net_history) - 1) if net_history[i] == previous]
        counts = [following.count(i) for i in (1, 2, 3)]
        return counter(counts.index(max(counts)) + 1)
    if kind == "noisy_cycle":
        return rng.randrange(1, 4) if rng.random() < 0.1 else t % 3 + 1
    if kind == "reactive":
        # If the previous throw lost, counter the network's last move;
        # otherwise follow a period-3 cycle. Uses previous outcomes only.
        return counter(net_history[-1]) if outcomes and outcomes[-1] > 0 else t % 3 + 1
    raise ValueError(kind)

def play(policy, kind, seed, start, length=100):
    rng = random.Random(seed)
    net_history = [x for x in start if x]
    bot_history = [x for x in start if x]
    outcomes = []
    hb = HINDEX[start]
    net = wins = losses = draws = 0
    for t in range(length):
        a = int(policy[hb])
        b = bot_move(kind, t, net_history, bot_history, outcomes, rng)
        v = score(a, b)
        net += v; wins += v > 0; losses += v < 0; draws += v == 0
        net_history.append(a);bot_history.append(b);outcomes.append(v)
        hb = int(NEXT[hb, b - 1])
    return net, wins, losses, draws
