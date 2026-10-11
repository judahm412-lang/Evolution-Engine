"""Environment plugins return evaluated fitness without depending on evolution."""
from dataclasses import dataclass, field
from typing import Protocol
import numpy as np
from .neural import sigmoid
from .rps_core import HISTORIES, INPUTS, NEXT, HINDEX, score, original_bot_moves

@dataclass
class Evaluation:
    total: np.ndarray
    self_play: np.ndarray
    bots: np.ndarray
    counts: np.ndarray  # matches, wins, losses, draws (outcomes are per throw)
    order: np.ndarray
    components: dict = field(default_factory=dict)
    policies: np.ndarray | None = None

class EnvironmentPlugin(Protocol):
    version: str
    def evaluate(self, population, config, rng, schedule=None) -> Evaluation: ...
    def reset(self, rng): ...
    def observe(self, state): ...
    def step(self, state, action): ...

def ordered_policies(genes):
    """Batch inference with v1 accumulation order, no BLAS reduction reordering."""
    g=np.asarray(genes,dtype=np.float64)
    w=g[:,:108].reshape(-1,12,9)
    h=INPUTS[None,:,0,None]*w[:,None,:,0]
    for j in range(1,9): h=h+INPUTS[None,:,j,None]*w[:,None,:,j]
    h=sigmoid(h+g[:,None,144:156])
    w=g[:,108:144].reshape(-1,3,12)
    o=h[:,:,0,None]*w[:,None,:,0]
    for j in range(1,12): o=o+h[:,:,j,None]*w[:,None,:,j]
    o=o+g[:,None,156:159]
    if np.any(o.max(axis=2)<=-1000):
        raise ValueError("Engine v1 produces invalid move -1000: all outputs <= -1000")
    return (o.argmax(axis=2)+1).astype(np.uint8),o

class PolicyCache:
    def __init__(self): self.values={}
    def get(self,population,compatibility):
        keys=[(g.fingerprint,compatibility) for g in population]
        missing=[i for i,k in enumerate(keys) if k not in self.values]
        if missing:
            if compatibility:
                policies,_=ordered_policies(np.stack([population[i].parameters for i in missing]))
            else:
                policies=np.stack([(population[i].forward(INPUTS).argmax(axis=1)+1).astype(np.uint8) for i in missing])
            for i,p in zip(missing,policies): self.values[keys[i]]=p
        # Bounded to the active population; immutable fingerprint avoids shuffled-slot bugs.
        self.values={k:self.values[k] for k in keys}
        return np.stack([self.values[k] for k in keys])

def make_schedule(n,env,rng):
    order=np.arange(n)
    orders=[]; bots=[]
    for _ in range(env.matches):
        order=rng.permutation(order)
        orders.append(order)
        kinds=rng.choice(env.opponents,n)
        offsets=rng.integers(0,3,n)
        bots.append(np.stack((kinds,offsets),axis=1))
    return np.array(orders),np.array(bots)

def validate_schedule(schedule,n,env):
    orders,bots=map(np.asarray,schedule)
    if orders.shape!=(env.matches,n) or bots.shape!=(env.matches,n,2): raise ValueError("schedule shape mismatch")
    if not np.issubdtype(orders.dtype,np.integer) or not np.issubdtype(bots.dtype,np.integer): raise ValueError("schedule must be integral")
    if any(not np.array_equal(np.sort(row),np.arange(n)) for row in orders): raise ValueError("each round must be a permutation")
    if not np.isin(bots[:,:,0],env.opponents).all() or not ((bots[:,:,1]>=0)&(bots[:,:,1]<3)).all(): raise ValueError("invalid bot schedule")
    return orders.astype(np.int64),bots.astype(np.int64)

def evaluate_numpy(p,orders,bots,rounds,bot_rounds,weight):
    n=len(p);s=np.zeros(n);b=np.zeros(n);total=np.zeros(n);counts=np.zeros((n,4),dtype=np.int64)
    for order,bot in zip(orders,bots):
        aidx,bidx=order[::2],order[1::2]
        ha=np.zeros(n//2,dtype=np.uint8);hb=ha.copy()
        for _ in range(rounds):
            a,c=p[aidx,hb],p[bidx,ha]
            v=(a.astype(int)-c.astype(int)+1)%3-1
            s[aidx]+=v;s[bidx]-=v;total[aidx]+=v;total[bidx]-=v
            counts[aidx,1]+=v>0;counts[aidx,2]+=v<0;counts[aidx,3]+=v==0
            counts[bidx,1]+=v<0;counts[bidx,2]+=v>0;counts[bidx,3]+=v==0
            ha,hb=NEXT[ha,a-1],NEXT[hb,c-1]
        hb=np.zeros(n,dtype=np.uint8);bs=np.zeros(n)
        for t in range(bot_rounds):
            v=(t+bot[:,1])%3
            moves=np.where(bot[:,0]==1,v+1,np.where(bot[:,0]==2,2*v%3+1,1+(v==2)))
            a=p[order,hb];v=(a.astype(int)-moves+1)%3-1
            bs+=v;counts[order,1]+=v>0;counts[order,2]+=v<0;counts[order,3]+=v==0
            hb=NEXT[hb,moves-1]
        b[order]+=bs;total[order]+=bs*weight;counts[:,0]+=2
    return total,s,b,counts

def _compiled_kernel(p,orders,bots,rounds,bot_rounds,weight,next_table):
    n=len(p);s=np.zeros(n);b=np.zeros(n);total=np.zeros(n);counts=np.zeros((n,4),dtype=np.int64)
    for r in range(len(orders)):
        order=orders[r]
        for pair in range(n//2):
            ia,ib=order[2*pair],order[2*pair+1];ha=hb=0
            for _ in range(rounds):
                a=int(p[ia,hb]);c=int(p[ib,ha]);v=(a-c+1)%3-1
                s[ia]+=v;s[ib]-=v;total[ia]+=v;total[ib]-=v
                counts[ia,1]+=v>0;counts[ia,2]+=v<0;counts[ia,3]+=v==0
                counts[ib,1]+=v<0;counts[ib,2]+=v>0;counts[ib,3]+=v==0
                ha,hb=next_table[ha,a-1],next_table[hb,c-1]
        for slot in range(n):
            idx=order[slot];kind,off=bots[r,slot];hb=0;bs=0
            for t in range(bot_rounds):
                v=(t+off)%3
                move=v+1 if kind==1 else (2*v)%3+1 if kind==2 else 1+int(v==2)
                a=int(p[idx,hb]);v=(a-move+1)%3-1;bs+=v
                counts[idx,1]+=v>0;counts[idx,2]+=v<0;counts[idx,3]+=v==0
                hb=next_table[hb,move-1]
            b[idx]+=bs;total[idx]+=bs*weight;counts[idx,0]+=2
    return total,s,b,counts

try:
    from numba import njit
except ImportError:
    compiled_kernel=None
else:
    compiled_kernel=njit(cache=True,fastmath=False)(_compiled_kernel)

class RPS:
    version="v1-source-1"
    def __init__(self): self.cache=PolicyCache()
    def evaluate(self,population,config,rng,schedule=None):
        env=config.environment
        p=self.cache.get(population,config.mode=='compatibility')
        orders,bots=validate_schedule(schedule if schedule is not None else make_schedule(len(p),env,rng),len(p),env)
        if config.execution.acceleration=='numba' and compiled_kernel is None: raise ValueError("install the accelerate extra for numba")
        if config.execution.acceleration!='numpy' and compiled_kernel is not None:
            total,s,b,counts=compiled_kernel(p,orders,bots,env.rounds,env.bot_rounds,env.bot_weight,NEXT)
        else: total,s,b,counts=evaluate_numpy(p,orders,bots,env.rounds,env.bot_rounds,env.bot_weight)
        if config.mode!='compatibility': total=s*env.self_weight+b*env.bot_weight
        return Evaluation(total,s,b,counts,orders[-1],policies=p)
    def reset(self,rng): return (0,0,0)
    def observe(self,state): return INPUTS[HINDEX[tuple(state)]].copy()
    def step(self,state,action):
        a,b=action
        if a not in (1,2,3) or b not in (1,2,3): raise ValueError("illegal RPS action")
        return (*state[1:],b),score(a,b),False

class Target:
    """One-step continuous-action target; any input/output size is supported."""
    version="target-1"
    def reset(self,rng): return {"done":False}
    def observe(self,state): return np.zeros(self.inputs)
    def step(self,state,action):
        return {"done":True},-float(np.mean((np.asarray(action)-self.target)**2)),True
    def evaluate(self,population,config,rng,schedule=None):
        self.inputs=population[0].layers[0];self.target=config.environment.target
        values=np.array([self.step(self.reset(rng),g.forward(np.zeros(self.inputs)))[1] for g in population])
        z=np.zeros(len(values));counts=np.zeros((len(values),4),dtype=np.int64);counts[:,0]=1
        return Evaluation(values,z,z,counts,np.arange(len(values)),{"target_reward":values.tolist()})

ENVIRONMENTS={"rps":RPS,"target":Target}

def create_environment(config): return ENVIRONMENTS[config.environment.type]()

def trace_match(a,b,length=23):
    ha=hb=0;trace=[]
    for t in range(length):
        x,y=int(a[hb]),int(b[ha]);trace.append({"round":t,"history_a":HISTORIES[ha],"history_b":HISTORIES[hb],"a":x,"b":y,"reward":score(x,y)})
        ha,hb=int(NEXT[ha,x-1]),int(NEXT[hb,y-1])
    return trace
