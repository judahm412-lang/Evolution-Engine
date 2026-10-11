"""Population transitions; independent of any task or dashboard."""
import numpy as np
from .neural import Genome

def rank(evaluation):
    # Python stable sort preserves the final shuffled list order for ties.
    return sorted(map(int,evaluation.order),key=lambda i:-evaluation.total[i])

def parent_indices(ranked,count,config,rng,fitness):
    e=config.evolution
    if e.selection=='top': return [ranked[i%e.elite_count] for i in range(count)]
    if e.selection=='rank':
        weights=np.arange(len(ranked),0,-1,dtype=float);weights/=weights.sum()
        return list(rng.choice(ranked,size=count,p=weights))
    chosen=[]
    for _ in range(count):
        candidates=rng.choice(ranked,size=min(e.tournament_size,len(ranked)),replace=False)
        chosen.append(max(candidates,key=lambda i:fitness[i]))
    return chosen

def mutate(parent,nid,generation,config,rng):
    e=config.evolution;p=parent.parameters.copy();attempts=0
    if config.mode=='compatibility':
        # Source interleaves an integer chance and (only if selected) a real delta.
        for j in range(len(p)):
            if rng.integers(1,101)<=10:
                attempts+=1;p[j]+=rng.uniform(-0.2,0.2)
    else:
        mask=rng.random(len(p))<e.probability
        if not e.mutate_weights: mask[:parent.weight_count]=False
        if not e.mutate_biases: mask[parent.weight_count:]=False
        attempts=int(mask.sum())
        if e.mutation=='gaussian': p[mask]+=rng.normal(0,e.magnitude,attempts)
        else: p[mask]+=rng.uniform(-e.magnitude,e.magnitude,attempts)
    changed=np.flatnonzero(p!=parent.parameters)
    changes=tuple((int(i),float(parent.parameters[i]),float(p[i])) for i in changed)
    return Genome(nid,parent.layers,parent.activations,p,parent.id,
                  generation if config.mode=='compatibility' else generation+1,generation+1,changes,attempts)

def reproduce(population,evaluation,config,rng,generation,next_id):
    ranked=rank(evaluation);n=config.population.size;e=config.evolution
    indices=parent_indices(ranked,n-e.elite_count,config,rng,evaluation.total)
    children=[mutate(population[int(i)],next_id+k,generation,config,rng) for k,i in enumerate(indices)]
    elites=[population[i] for i in ranked[:e.elite_count]]
    return children+elites,next_id+len(children)

def cluster_labels(genes,k=4):
    k=min(k,len(genes));centers=[genes[np.argmin(np.linalg.norm(genes-genes.mean(axis=0),axis=1))]]
    for _ in range(k-1):
        d=np.min([np.sum((genes-c)**2,axis=1) for c in centers],axis=0)
        centers.append(genes[int(np.argmax(d))])
    centers=np.array(centers);labels=np.full(len(genes),-1)
    for _ in range(30):
        new=np.argmin([np.sum((genes-c)**2,axis=1) for c in centers],axis=0)
        if np.array_equal(new,labels): break
        labels=new
        for i in range(k):
            if np.any(labels==i):centers[i]=genes[labels==i].mean(axis=0)
    return labels

def statistics(population,evaluation):
    f=evaluation.total;g=np.stack([x.parameters for x in population]);n=len(g)
    # RMS over all distinct pairs, computed via variance without an N*N*P tensor.
    gd=float(np.sqrt(2*n/(n-1)*g.var(axis=0).mean()))
    labels=cluster_labels(g);p=evaluation.policies
    bd=None;unique=None
    if p is not None:
        agreements=sum((p==move).sum(axis=0)*((p==move).sum(axis=0)-1) for move in (1,2,3))
        bd=float((1-agreements/(n*(n-1))).mean());unique=len({q.tobytes() for q in p})
    hist,edges=np.histogram(f,bins=12)
    return {"mean":float(f.mean()),"maximum":float(f.max()),"minimum":float(f.min()),
            "std":float(f.std()),"self_mean":float(evaluation.self_play.mean()),"bot_mean":float(evaluation.bots.mean()),
            "genetic_rms":gd,"behavioral_hamming":bd,"unique_policies":unique,
            "clusters":int(len(set(labels))),"cluster_sizes":np.bincount(labels).tolist(),
            "mutation_mean":float(np.mean([len(x.mutations) for x in population])),
            "histogram":{"counts":hist.tolist(),"edges":edges.tolist()},"champion_id":population[rank(evaluation)[0]].id}
