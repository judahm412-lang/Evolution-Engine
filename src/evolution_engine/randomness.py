"""Explicit PCG64 streams and recorded draw injection for differential tests."""
import numpy as np

def streams(seed):
    children=np.random.SeedSequence(seed).spawn(3)
    return {name:np.random.default_rng(child) for name,child in zip(('initialization','evaluation','reproduction'),children)}

def states(rngs):
    return {key:rng.bit_generator.state for key,rng in rngs.items()}

def restore(saved):
    result={}
    for key,state in saved.items():
        if state['bit_generator']!='PCG64': raise ValueError("unsupported RNG")
        result[key]=np.random.default_rng();result[key].bit_generator.state=state
    return result

class DrawTape:
    """Inject ordered, already-scaled integer/float draws into mutation."""
    def __init__(self,draws): self.draws=iter(draws)
    def integers(self,low,high):
        x=next(self.draws)
        if type(x) is not int or not low<=x<high: raise ValueError("invalid integer tape draw")
        return x
    def uniform(self,low,high):
        x=next(self.draws)
        if not low<=x<=high: raise ValueError("invalid uniform tape draw")
        return float(x)
