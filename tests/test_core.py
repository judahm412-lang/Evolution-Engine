import importlib.util
from pathlib import Path
import numpy as np
import pytest
from evolution_engine.config import Config
from evolution_engine.neural import Genome, initialize, ACTIVATIONS, genetic_distance
from evolution_engine.environments import ordered_policies, PolicyCache, RPS, Target, make_schedule, evaluate_numpy, compiled_kernel
from evolution_engine.evolution import mutate, reproduce, rank, statistics
from evolution_engine.randomness import streams, DrawTape
from evolution_engine.rps_core import HISTORIES, NEXT, INPUTS, batch_matches, match

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('experiment8_reference',ROOT/'experiment_08/src/engine.py')
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)

def small(**updates):
    raw={'mode':'general','population':{'size':10},'evolution':{'elite_count':2},'environment':{'matches':3},'generations':4}
    raw.update(updates);return Config.model_validate(raw)

def test_differential_all_reachable_histories():
    rng=np.random.default_rng(49);g=rng.normal(0,.7,(12,159))
    p,o=ordered_policies(g);q,z=reference.policies(g)
    assert np.array_equal(p,q)
    np.testing.assert_allclose(o,z,atol=1e-12,rtol=1e-12)
    for i in range(len(g)):
        for j,h in enumerate(HISTORIES):
            np.testing.assert_allclose(o[i,j],reference.scratch_outputs(g[i],h),atol=1e-12)
            assert p[i,j]==reference.scratch_move(g[i],h)

def test_tie_and_invalid_sentinel():
    assert np.all(ordered_policies(np.zeros((1,159)))[0]==1)
    g=np.zeros((1,159));g[:,156:]=-1001
    with pytest.raises(ValueError,match='-1000'):ordered_policies(g)

@pytest.mark.parametrize('activation',list(ACTIVATIONS))
def test_forward_and_immutable(activation):
    g=Genome(1,(2,3,2),(activation,'linear'),np.arange(17)/17)
    x=np.array([[0,1],[2,-1],[1,1]])
    np.testing.assert_allclose(g.forward(x),np.stack([g.forward(i) for i in x]))
    assert Genome(**g.record()).fingerprint==g.fingerprint
    with pytest.raises(ValueError):g.parameters[0]=99
    with pytest.raises(ValueError):g.parameters.setflags(write=True)

def test_compat_neural_matches_policy():
    g=initialize(Config(),np.random.default_rng(2))[0]
    _,o=ordered_policies(g.parameters[None,:])
    np.testing.assert_array_equal(g.forward(INPUTS,True),o[0])

@pytest.mark.parametrize('bad',[{'population':{'size':98}},{'evolution':{'probability':.2}},{'mode':'garbage'},{'unused':2},{'seed':-1},{'generations':1.5},{'environment':{'bot_weight':float('nan')}}])
def test_invalid_config(bad):
    with pytest.raises(ValueError):Config.model_validate(bad)

def test_mutation_draw_tape_and_copy():
    g=initialize(Config(),np.random.default_rng(5))[0]
    draws=[1,0.0,1,.2]+[100]*157
    child=mutate(g,101,0,Config(),DrawTape(draws))
    assert child.parent_id==1 and child.first_generation==1 and child.birth_generation==0
    assert child.attempted_mutations==2 and len(child.mutations)==1
    assert child.mutations[0][0]==1
    assert genetic_distance(g,child)>0
    assert not np.shares_memory(g.parameters,child.parameters)

def test_source_reproduction_order():
    c=Config();r=streams(12);p=initialize(c,r['initialization']);e=RPS().evaluate(p,c,r['evaluation'])
    nxt,nid=reproduce(p,e,c,r['reproduction'],0,101)
    ids=[p[i].id for i in rank(e)[:20]]
    assert [g.parent_id for g in nxt[:80]]==ids*4
    assert [g.id for g in nxt[80:]]==ids
    assert nid==181 and len({g.id for g in nxt})==100

@pytest.mark.parametrize('method',['top','tournament','rank'])
def test_selection(method):
    c=small(evolution={'elite_count':2,'selection':method});r=streams(2)
    p=initialize(c,r['initialization']);e=RPS().evaluate(p,c,r['evaluation'])
    nxt,_=reproduce(p,e,c,r['reproduction'],0,11)
    assert {p[i].id for i in rank(e)[:2]}=={g.id for g in nxt[-2:]}

def test_cache_shuffle_and_kernels():
    c=small();r=streams(99);p=initialize(c,r['initialization']);cache=PolicyCache()
    a=cache.get(p,True);b=cache.get(p[::-1],True);assert np.array_equal(a,b[::-1])
    order,bots=make_schedule(10,c.environment,r['evaluation'])
    expected=evaluate_numpy(a,order,bots,23,20,.17)
    if compiled_kernel:
        actual=compiled_kernel(a,order,bots,23,20,.17,NEXT)
        for x,y in zip(expected,actual):np.testing.assert_array_equal(x,y)
    for i in range(10):assert expected[3][i,1:].sum()==3*43
    assert expected[1].sum()==0

def test_tournament_and_trace():
    rng=np.random.default_rng(9);p=rng.integers(1,4,(4,40),dtype=np.uint8)
    result=batch_matches(p,p,23)
    assert np.array_equal(result[0],-result[0].T)
    for i in range(4):
        for j in range(4):assert tuple(int(x[i,j]) for x in result)==reference.match(p[i],p[j])

def test_non_rps():
    c=small(environment={'type':'target'},population={'size':10,'network':{'layers':[2,5,7],'activations':['tanh','linear']} })
    r=streams(11);p=initialize(c,r['initialization']);e=Target().evaluate(p,c,r['evaluation'])
    assert len(e.total)==10 and max(e.total)<=0
    assert statistics(p,e)['behavioral_hamming'] is None
