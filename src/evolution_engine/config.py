"""Strict, resolved experiment configuration. Compatibility is never inferred."""
from pathlib import Path
from typing import Literal
import json
import tomllib
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)

class Network(Model):
    layers: list[int] = Field(default_factory=lambda: [9, 12, 3], min_length=2, max_length=8)
    activations: list[str] = Field(default_factory=lambda: ["sigmoid", "linear"])
    initialization: Literal["uniform", "normal", "zeros"] = "uniform"

    @model_validator(mode="after")
    def dimensions(self):
        if any(type(n) is not int or not 1 <= n <= 1024 for n in self.layers):
            raise ValueError("layer sizes must be integers between 1 and 1024")
        if len(self.activations) != len(self.layers) - 1:
            raise ValueError("one activation is required for each non-input layer")
        from .neural import ACTIVATIONS
        if any(a not in ACTIVATIONS for a in self.activations):
            raise ValueError(f"activations must be registered: {list(ACTIVATIONS)}")
        if sum(a*b+b for a,b in zip(self.layers, self.layers[1:])) > 1000000:
            raise ValueError("network exceeds one million parameters")
        return self

class Population(Model):
    size: int = Field(100, ge=2, le=1000, strict=True)
    network: Network = Field(default_factory=Network)

class Evolution(Model):
    selection: Literal["top", "tournament", "rank"] = "top"
    elite_count: int = Field(20, ge=1, strict=True)
    tournament_size: int = Field(3, ge=2, strict=True)
    reproduction: Literal["asexual"] = "asexual"
    mutation: Literal["uniform", "gaussian"] = "uniform"
    probability: float = Field(0.1, ge=0, le=1)
    magnitude: float = Field(0.2, ge=0, le=100)
    mutate_weights: bool = True
    mutate_biases: bool = True

class Environment(Model):
    type: Literal["rps", "target"] = "rps"
    matches: int = Field(30, ge=1, le=1000, strict=True)
    rounds: int = Field(23, ge=1, le=10000, strict=True)
    bot_rounds: int = Field(20, ge=1, le=10000, strict=True)
    bot_weight: float = Field(0.25, ge=0, le=1000)
    self_weight: float = Field(1, ge=0, le=1000)
    opponents: list[int] = Field(default_factory=lambda: [1, 2, 3], min_length=1)
    target: float = Field(0.5, ge=-100, le=100)

class Execution(Model):
    workers: int = Field(2, ge=1, le=16, strict=True)
    checkpoint_frequency: int = Field(10, ge=1, strict=True)
    checkpoint_retention: int = Field(10, ge=1, le=10000, strict=True)
    history_stride: int = Field(1, ge=1, strict=True)
    acceleration: Literal["numpy", "numba", "auto"] = "auto"
    retries: int = Field(1, ge=0, le=5, strict=True)
    priority: int = Field(0, ge=-100, le=100, strict=True)

class StorageConfig(Model):
    export_compression: bool = True
    archive_policy: Literal["retain"] = "retain"

class Config(Model):
    name: str = Field("RPS compatibility", min_length=1, max_length=120)
    description: str = Field("", max_length=4000)
    experiment_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    mode: Literal["compatibility", "general"] = "compatibility"
    generations: int = Field(1000, ge=1, le=1000000, strict=True)
    replicates: int = Field(1, ge=1, le=100, strict=True)
    seed: int = Field(42, ge=0, le=2**63-1, strict=True)
    population: Population = Field(default_factory=Population)
    evolution: Evolution = Field(default_factory=Evolution)
    environment: Environment = Field(default_factory=Environment)
    execution: Execution = Field(default_factory=Execution)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    @model_validator(mode="after")
    def consistent(self):
        p, e, env = self.population, self.evolution, self.environment
        if e.elite_count >= p.size:
            raise ValueError("elite_count must be smaller than population size")
        if env.type == "rps":
            if p.size % 2 or p.network.layers[0] != 9 or p.network.layers[-1] != 3:
                raise ValueError("RPS requires an even population, 9 inputs and 3 outputs")
            if any(x not in (1,2,3) for x in env.opponents):
                raise ValueError("RPS opponents must be 1, 2, or 3")
        if self.mode == "compatibility":
            if p != Population() or e != Evolution() or env.type != "rps" or (env.matches, env.rounds, env.bot_rounds, env.self_weight, env.opponents) != (30,23,20,1,[1,2,3]):
                raise ValueError("compatibility fixes 100 networks, 9/12/3 sigmoid/linear, top 20, 10% uniform ±0.2 mutation, 30 × (23 self + 20 bot throws); use general mode for other settings")
        return self

def load_config(path):
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f) if path.suffix == ".toml" else json.load(f)
    return Config.model_validate(raw)
