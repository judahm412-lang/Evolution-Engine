"""Small test-only interpreter of the actual project blocks, not a hand port.

Supports only opcodes needed by inference, selection, mutation and one tournament
round. Unsupported opcodes fail loudly. It is not the TurboWarp JavaScript VM.
"""
import json
import math
import zipfile

class Returned(Exception):
    def __init__(self,value):self.value=value

class VM:
    def __init__(self,path,draws=()):
        p=json.loads(zipfile.ZipFile(path).read('project.json'))
        self.b=p['targets'][1]['blocks'];self.variables={};self.lists={};self.procedures={};self.draws=iter(draws)
        for t in p['targets']:
            self.variables.update({v[0]:v[1] for v in t['variables'].values()})
            self.lists.update({v[0]:list(v[1]) for v in t['lists'].values()})
        for block in self.b.values():
            if block['opcode']=='procedures_definition':
                proto=self.b[block['inputs']['custom_block'][1]];m=proto['mutation']
                self.procedures[m['proccode']]=(json.loads(m['argumentnames']),json.loads(m['argumentids']),block['next'])
        self.args={};self.activation_trace=[]
    def number(self,x):
        try:return float(x)
        except (ValueError,TypeError):return 0.
    def value(self,v):
        if isinstance(v,list):
            if v[0]==12:return self.variables[v[1]]
            if v[0]==13:return self.lists[v[1]]
            return v[1]
        if v is None:return ''
        x=self.b[v];op=x['opcode'];f={k:a[0] for k,a in x.get('fields',{}).items()}
        def arg(k):return self.value(x['inputs'][k][1])
        def num(k):return self.number(arg(k))
        if op=='argument_reporter_string_number':return self.args[f['VALUE']]
        if op=='data_variable':return self.variables[f['VARIABLE']]
        if op=='data_itemoflist':
            i=int(num('INDEX'))-1;l=self.lists[f['LIST']];return l[i] if 0<=i<len(l) else ''
        if op=='data_itemnumoflist':
            l=self.lists[f['LIST']];item=arg('ITEM');return l.index(item)+1 if item in l else 0
        if op=='data_lengthoflist':return len(self.lists[f['LIST']])
        if op=='operator_add':return num('NUM1')+num('NUM2')
        if op=='operator_subtract':return num('NUM1')-num('NUM2')
        if op=='operator_multiply':return num('NUM1')*num('NUM2')
        if op=='operator_divide':return num('NUM1')/num('NUM2')
        if op=='operator_mod':return num('NUM1')%num('NUM2')
        if op=='operator_equals':
            a,b=arg('OPERAND1'),arg('OPERAND2')
            try:return float(a)==float(b)
            except (ValueError,TypeError):return str(a).lower()==str(b).lower()
        if op=='operator_gt':return num('OPERAND1')>num('OPERAND2')
        if op=='truefantommath_less_or_equal_block':return num('A')<=num('B')
        if op=='operator_mathop':
            if f['OPERATOR']!='e ^':raise NotImplementedError(f)
            try:return math.exp(num('NUM'))
            except OverflowError:return math.inf
        if op=='operator_random':
            result=next(self.draws)
            assert num('FROM')<=result<=num('TO')
            return result
        if op=='lmsData_menu_lists':return f['lists']
        if op=='lmsData_getListArray':return json.dumps(self.lists[arg('LIST')])
        if op=='skyhigh173JSON_json_array_get':return json.loads(arg('json'))[int(num('item'))-1]
        if op=='skyhigh173JSON_json_array_set':
            l=json.loads(arg('json'));l[int(num('pos'))-1]=arg('item');return json.dumps(l)
        if op=='procedures_call':
            names,ids,_=self.procedures[x['mutation']['proccode']]
            return self.call(x['mutation']['proccode'],*[arg(i) for i in ids])
        raise NotImplementedError(op)
    def call(self,name,*values):
        names,ids,k=self.procedures[name];saved=self.args;self.args=dict(zip(names,values))
        try:self.execute(k)
        except Returned as r:return r.value
        finally:self.args=saved
    def execute(self,k):
        while k:
            x=self.b[k];op=x['opcode'];f={a:v[0] for a,v in x.get('fields',{}).items()}
            def arg(name):return self.value(x['inputs'][name][1])
            def sub(name='SUBSTACK'):self.execute(x['inputs'][name][1])
            if op=='data_setvariableto':self.variables[f['VARIABLE']]=arg('VALUE')
            elif op=='data_changevariableby':self.variables[f['VARIABLE']]=self.number(self.variables[f['VARIABLE']])+self.number(arg('VALUE'))
            elif op=='data_deletealloflist':self.lists[f['LIST']]=[]
            elif op=='data_addtolist':self.lists[f['LIST']].append(arg('ITEM'))
            elif op=='data_replaceitemoflist':self.lists[f['LIST']][int(self.number(arg('INDEX')))-1]=arg('ITEM')
            elif op=='data_deleteoflist':del self.lists[f['LIST']][int(self.number(arg('INDEX')))-1]
            elif op=='lmsData_joinLists':
                self.lists[arg('LIST2')].extend(self.lists[arg('LIST1')])
                if arg('LIST2')=='master input list':self.activation_trace.append(list(self.lists[arg('LIST2')]))
            elif op=='lmsData_setListArray':self.lists[arg('LIST')]=json.loads(arg('ARRAY'))
            elif op=='control_repeat':
                for _ in range(round(self.number(arg('TIMES')))):sub()
            elif op=='control_repeat_until':
                limit=0
                while not arg('CONDITION'):
                    sub();limit+=1
                    if limit>100000:raise ValueError('runaway loop')
            elif op in ('control_if','control_if_else'):
                if arg('CONDITION'):sub()
                elif op=='control_if_else':sub('SUBSTACK2')
            elif op=='procedures_call':self.value(k)
            elif op=='procedures_return':raise Returned(arg('VALUE'))
            elif op=='lmscomments_commentC':sub()
            elif op in ('lmsTimers_startResetTimer','lmsTimers_pauseTimer'):pass
            else:raise NotImplementedError(op)
            k=x.get('next')
