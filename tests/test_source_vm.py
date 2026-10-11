import json
import numpy as np
from sb3_vm import VM
from test_core import ROOT
from evolution_engine.config import Config
from evolution_engine.neural import initialize
from evolution_engine.environments import ordered_policies,RPS
from evolution_engine.evolution import mutate,rank
from evolution_engine.randomness import DrawTape
from evolution_engine.rps_core import HISTORIES,INPUTS

def record(g,fitness=0):return json.dumps([g.id,json.dumps(g.parameters[:144].tolist()),json.dumps(g.parameters[144:].tolist()),fitness,g.birth_generation,g.attempted_mutations,g.parent_id or 0])

def test_actual_source_inference():
    vm=VM(ROOT/'engineV1.sb3');pop=initialize(Config(),np.random.default_rng(713))[:3]
    for g in pop:
        p,o=ordered_policies(g.parameters[None,:])
        vm.lists['master weights list']=g.parameters[:144].tolist();vm.lists['master biases list']=g.parameters[144:].tolist()
        for hi,h in enumerate(HISTORIES):
            vm.lists['master input list']=INPUTS[hi].tolist();vm.call('compute uncached model')
            assert vm.variables['highest index']==p[0,hi]
            np.testing.assert_allclose(vm.lists['master input list'],o[0,hi],atol=1e-12)

def test_actual_source_mutation():
    c=Config();g=initialize(c,np.random.default_rng(61))[0]
    draws=[1,.2,100,5,-.17]+[100]*156
    vm=VM(ROOT/'engineV1.sb3',draws);vm.lists['sorted models']=[record(g)];vm.lists['model list']=[]
    vm.variables['on for model making']=100;vm.variables['gen on']=7
    vm.call('mutate a model %s',1)
    raw=json.loads(vm.lists['model list'][0]);child=mutate(g,101,7,c,DrawTape(draws))
    np.testing.assert_array_equal(json.loads(raw[1])+json.loads(raw[2]),child.parameters)
    assert list(map(int,[raw[0],raw[4],raw[5],raw[6]]))==[child.id,child.birth_generation,child.attempted_mutations,child.parent_id]

def test_actual_source_round_and_selection():
    c=Config();p=initialize(c,np.random.default_rng(44));rng=np.random.default_rng(53)
    order=rng.permutation(100);bots=np.stack([rng.integers(1,4,100),rng.integers(0,3,100)],axis=1)
    vm=VM(ROOT/'engineV1.sb3',bots.flatten().tolist());vm.variables['bot weight']=.25
    vm.lists['model list']=[record(p[int(i)]) for i in order]
    vm.lists['opt cache network IDs']=[g.id for g in p]
    vm.lists['opt cached moves']=[0]*6400;vm.call('refresh cache mapping');vm.call('run all one time')
    # Repeat this exact schedule thirty times in Python and divide the components.
    ev=RPS().evaluate(p,c,rng,(np.tile(order,(30,1)),np.tile(bots,(30,1,1))))
    scores=[json.loads(r)[3] for r in vm.lists['model list']]
    np.testing.assert_array_equal(scores,ev.total[order]/30)
    vm.call('sort into top 20 models list')
    selected=[int(json.loads(r)[0]) for r in vm.lists['sorted models']]
    assert selected==[p[i].id for i in rank(ev)[:20]]
