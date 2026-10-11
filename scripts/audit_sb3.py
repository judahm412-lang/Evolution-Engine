"""Render source blocks without modifying the authoritative archive."""
import json
import sys
import zipfile

p = json.loads(zipfile.ZipFile(sys.argv[1]).read("project.json"))
b = p["targets"][1]["blocks"]

def expr(v):
    if isinstance(v, list):
        return str(v[1])
    if v not in b:
        return str(v)
    x = b[v]
    op = x['opcode']
    fields = [str(f[0]) for f in x.get('fields', {}).values()]
    args = [f'{k}={expr(i[1])}' for k, i in x.get('inputs', {}).items() if not k.startswith('SUBSTACK')]
    if op == 'procedures_call':
        op = x['mutation']['proccode']
    return op + '(' + ', '.join(fields + args) + ')'

def walk(k, depth=0):
    while k:
        x = b[k]
        print(' ' * depth + k + ': ' + expr(k))
        for f in ('SUBSTACK', 'SUBSTACK2'):
            if f in x.get('inputs', {}):
                if f == 'SUBSTACK2': print(' ' * depth + 'ELSE')
                walk(x['inputs'][f][1], depth + 2)
        k = x.get('next')

for k, x in b.items():
    if x.get('topLevel'):
        if x['opcode'] == 'procedures_definition':
            print('\nPROCEDURE', b[x['inputs']['custom_block'][1]]['mutation'])
            walk(x.get('next'))
        elif x['opcode'].startswith('event'):
            print('\nEVENT')
            walk(k)
