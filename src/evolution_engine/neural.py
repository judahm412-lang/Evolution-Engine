"""Immutable genomes; all weights first, followed by all biases (v1 ordering)."""
from dataclasses import dataclass
from hashlib import sha256
import json
import numpy as np

def sigmoid(x):
    with np.errstate(over="ignore"):
        return 1.0 / (1.0 + np.exp(-x))

def softmax(x):
    y = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return y / y.sum(axis=-1, keepdims=True)

ACTIVATIONS = {"sigmoid": sigmoid, "relu": lambda x: np.maximum(x,0),
               "tanh": np.tanh, "linear": lambda x:x, "softmax": softmax}

def register_activation(name, function):
    if not name or name in ACTIVATIONS or not callable(function):
        raise ValueError("activation name must be new and function callable")
    ACTIVATIONS[name] = function

def parameter_count(layers):
    return sum(a*b+b for a,b in zip(layers,layers[1:]))

@dataclass(frozen=True, eq=False)
class Genome:
    id: int
    layers: tuple[int,...]
    activations: tuple[str,...]
    parameters: np.ndarray
    parent_id: int | None = None
    birth_generation: int = 0
    first_generation: int = 0
    mutations: tuple = ()
    attempted_mutations: int = 0

    def __post_init__(self):
        object.__setattr__(self,"layers",tuple(self.layers))
        object.__setattr__(self,"activations",tuple(self.activations))
        if len(self.layers)<2 or any(type(n) is not int or n<1 for n in self.layers):
            raise ValueError("invalid network architecture")
        if len(self.activations)!=len(self.layers)-1 or any(a not in ACTIVATIONS for a in self.activations):
            raise ValueError("invalid activation functions")
        p=np.asarray(self.parameters,dtype=np.float64)
        if p.shape != (parameter_count(self.layers),) or not np.isfinite(p).all():
            raise ValueError("invalid parameter count or nonfinite genome")
        if self.id<1 or self.parent_id == self.id:
            raise ValueError("invalid identity or self-parent")
        # bytes-backed arrays cannot be made writable again by callers.
        object.__setattr__(self,"parameters",np.frombuffer(p.astype('<f8').tobytes(),dtype='<f8'))
        object.__setattr__(self,"mutations",tuple(tuple(m) for m in self.mutations))

    @property
    def weight_count(self):
        return sum(a*b for a,b in zip(self.layers,self.layers[1:]))

    @property
    def fingerprint(self):
        return sha256(json.dumps([self.layers,self.activations]).encode()+self.parameters.tobytes()).hexdigest()

    def record(self):
        return {"id":self.id,"layers":self.layers,"activations":self.activations,
                "parameters":self.parameters.tolist(),"parent_id":self.parent_id,
                "birth_generation":self.birth_generation,"first_generation":self.first_generation,
                "mutations":self.mutations,"attempted_mutations":self.attempted_mutations}

    def forward(self, observations, compatibility=False):
        x=np.asarray(observations,dtype=np.float64)
        if x.ndim<1 or x.shape[-1]!=self.layers[0] or not np.isfinite(x).all():
            raise ValueError("invalid observations")
        wi,bi=0,self.weight_count
        for inputs,outputs,activation in zip(self.layers,self.layers[1:],self.activations):
            w=self.parameters[wi:wi+inputs*outputs].reshape(outputs,inputs)
            if compatibility:
                y=x[...,0,None]*w[:,0]
                for j in range(1,inputs):
                    y=y+x[...,j,None]*w[:,j]
            else:
                y=x@w.T
            x=ACTIVATIONS[activation](y+self.parameters[bi:bi+outputs])
            wi+=inputs*outputs; bi+=outputs
        return x

def initialize(config,rng):
    n=config.population.network
    count=parameter_count(n.layers)
    if n.initialization=='uniform':
        p=rng.uniform(-1,1,(config.population.size,count))
    elif n.initialization=='normal':
        p=rng.normal(0,1,(config.population.size,count))
    else:
        p=np.zeros((config.population.size,count))
    return [Genome(i+1,tuple(n.layers),tuple(n.activations),row) for i,row in enumerate(p)]

def genetic_distance(a,b):
    if a.layers!=b.layers or a.activations!=b.activations:
        raise ValueError("genetic distance requires matching architectures")
    return float(np.sqrt(np.mean((a.parameters-b.parameters)**2)))
