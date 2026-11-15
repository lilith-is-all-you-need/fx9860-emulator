"""Real newly built counter C/C++ G1As, native GDB MI and screen/key integration.

Requires the root build validation to have produced each example's Debug and
Release artifacts. Never substitutes historical KhiCAS fixtures.
"""
from pathlib import Path
import hashlib,json,os,queue,re,shutil,socket,subprocess,threading,time
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'probes/emulator/build/native-examples'
OUT.mkdir(parents=True,exist_ok=True)
EMULATOR=ROOT/'probes/emulator/build/FxEmulator.exe'
GDB=ROOT/'dist-toolchain/native-gdb/runtime/gdb/bin/gdb.exe'
ASCII=Path.home()/'.codex-build-envs/native-sdk-20261114/native-debug-tests'
ASCII.mkdir(parents=True,exist_ok=True)
ENV=dict(os.environ,PATH=str(Path(os.environ['SYSTEMROOT'])/'System32'),PYTHONUTF8='1')

class MI:
    def __init__(self,elf,work):
        self.log=[];self.lines=queue.Queue();self.stops=queue.Queue();self.token=0
        self.process=subprocess.Popen([str(GDB),'--interpreter=mi2','-nx','-nh','--quiet',str(elf)],cwd=work,env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
        def reader():
            for line in self.process.stdout:
                line=line.rstrip();self.log.append(line)
                if line.startswith('*stopped'): self.stops.put(line)
                self.lines.put(line)
        self.thread=threading.Thread(target=reader,daemon=True);self.thread.start()
    def command(self,command):
        self.token+=1;prefix=str(self.token)
        self.log.append('> '+prefix+command)
        self.process.stdin.write(prefix+command+'\n');self.process.stdin.flush()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try: line=self.lines.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty: break
            if line.startswith(prefix+'^'):
                if '^error' in line: raise RuntimeError('GDB command failed: '+command+'\n'+line)
                return line
        raise TimeoutError('GDB command timed out: '+command)
    def clear_stops(self):
        while not self.stops.empty(): self.stops.get_nowait()
    def stopped(self):
        try: return self.stops.get(timeout=15)
        except queue.Empty: raise TimeoutError('Target did not stop')
    def advance(self,command):
        self.clear_stops();self.command(command);return self.stopped()
    def value(self,expression):
        reply=self.command('-data-evaluate-expression '+json.dumps(expression))
        match=re.search(r',value=("(?:[^"\\]|\\.)*")',reply)
        if not match: raise RuntimeError('No MI expression value: '+reply)
        return json.loads(match.group(1))
    def close(self):
        if self.process.poll() is None:
            try:self.command('-gdb-exit')
            except Exception: self.process.terminate()
            self.process.wait(timeout=5)

def pixels(path):
    data=path.read_bytes()
    assert data[:2]==b'BM' and len(data)>54,'No fresh BMP'
    start=int.from_bytes(data[10:14],'little')
    assert int.from_bytes(data[18:22],'little')==128
    assert int.from_bytes(data[22:26],'little')==64
    return data[start:]

def verify(example,profile):
    key=example+'-'+profile
    project=ROOT/'examples'/example
    build=project/'.fxstudio/build'/profile
    manifest=json.loads((build/'artifact.json').read_text(encoding='utf-8'))
    assert manifest['pathStyle']=='windows' and manifest['configuration']==profile
    assert 'Native fxSDK' in manifest['toolchain'] and manifest['artifactPair']['verified']
    work=ASCII/key;work.mkdir(exist_ok=True)
    elf=work/'addin.elf';g1a=work/'addin.g1a'
    shutil.copy2(manifest['elf'],elf);shutil.copy2(manifest['g1a'],g1a)
    for field,file in (('elf',elf),('g1a',g1a)):
        assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest['sha256'][field]
    value_expression='counter.value' if profile=='Debug' else '*(int *)&counter'
    updates_expression='counter.updates' if profile=='Debug' else ('((unsigned *)&counter)[2]' if example.endswith('cpp') else '((unsigned *)&counter)[1]')
    frame=work/'screen.bmp';frame.unlink(missing_ok=True)
    stderr=(OUT/(key+'-emulator.log')).open('w',encoding='utf-8')
    process=subprocess.Popen([str(EMULATOR),'--gdb-port','0','--control-port','0','--framebuffer',str(frame),str(g1a)],cwd=work,env=ENV,stdout=subprocess.PIPE,stderr=stderr,text=True,encoding='utf-8')
    mi=None;control=None;stream=None;checks=[]
    def checked(name):checks.append(name);print('PASS '+key+': '+name,flush=True)
    try:
        ready=json.loads(process.stdout.readline())
        control=socket.create_connection(('127.0.0.1',ready['controlPort']),timeout=5)
        stream=control.makefile('rwb')
        def ctrl(command):
            stream.write((json.dumps(command)+'\n').encode());stream.flush()
            result=json.loads(stream.readline())
            if not result['ok']: raise RuntimeError('Emulator control failed: '+str(result))
            return result
        def press(keyname):
            ctrl({'command':'key','key':keyname,'down':True});time.sleep(.12)
            ctrl({'command':'key','key':keyname,'down':False})
        mi=MI(elf,work)
        mi.command('-gdb-set pagination off');mi.command('-gdb-set confirm off')
        mi.command('-gdb-set mi-async on')
        mi.command('-gdb-set architecture sh4al-dsp');mi.command('-gdb-set endian big')
        for mapping in manifest['sourceMappings']:
            command='set substitute-path '+json.dumps(mapping['from'],ensure_ascii=False)+' '+json.dumps(mapping['to'].replace('\\','/'),ensure_ascii=False)
            mi.command('-interpreter-exec console '+json.dumps(command,ensure_ascii=False))
        mi.command('-target-select remote 127.0.0.1:'+str(ready['gdbPort']))
        mi.command('-break-insert main')
        stop=mi.advance('-exec-continue')
        assert 'func="main"' in stop,stop
        assert mi.value(value_expression)=='0'
        checked('fresh native ELF main breakpoint and zero-valued real counter')
        if profile=='Debug':
            assert 'fullname=' in stop and 'main.' in stop
            stop=mi.advance('-exec-next')
            stop=mi.advance('-exec-next') # gint_setrestart, then the first draw
            initial=pixels(frame)
            assert len(set(initial))>1,'Initial drawing was not flushed at source stop'
            shutil.copy2(frame,OUT/(key+'-initial.bmp'))
            checked('source next executes initial drawing and paused framebuffer is fresh')
            mi.command('-break-insert change_counter')
            mi.clear_stops();mi.command('-exec-continue');time.sleep(.25);press('PLUS')
            stop=mi.stopped();assert 'change_counter' in stop,stop
            assert mi.value('delta')=='1'
            state_expression='state.value' if example.endswith('cpp') else 'state->value'
            assert mi.value(state_expression)=='0'
            variables=mi.command('-stack-list-variables --all-values')
            assert 'name="state"' in variables and 'name="delta"' in variables
            stack=mi.command('-stack-list-frames')
            assert 'change_counter' in stack and 'func="main"' in stack
            checked('actual PLUS press reaches source breakpoint with pointer/reference argument, delta and call stack')
            saw_previous=False
            for _ in range(12):
                variables=mi.command('-stack-list-variables --all-values')
                if 'name="previous",value="0"' in variables:saw_previous=True
                stop=mi.advance('-exec-step')
                if 'clamp_counter' in stop:break
            else:raise AssertionError('Source step did not enter clamp_counter')
            assert saw_previous,'Local previous was not observed as zero before function call'
            assert mi.value('value')=='1'
            stack=mi.command('-stack-list-frames')
            assert 'clamp_counter' in stack and 'change_counter' in stack and 'func="main"' in stack
            checked('source step enters noinline clamp_counter; local previous, parameter and three-frame stack are visible')
            stop=mi.advance('-exec-finish');assert 'change_counter' in stop,stop
            stop=mi.advance('-exec-finish');assert 'func="main"' in stop,stop
            assert mi.value('counter.value')=='1' and mi.value('counter.updates')=='1'
            registers=mi.command('-data-list-register-values x 0 15 16')
            assert 'register-values=' in registers and 'value="0x' in registers
            memory=mi.command('-data-read-memory-bytes "&counter" 8')
            assert 'contents="00000001' in memory,memory
            checked('two finish operations return to main; counter state, registers and memory agree')
        else:
            mi.command('-break-delete')
            mi.clear_stops();mi.command('-exec-continue');time.sleep(.45)
            mi.advance('-exec-interrupt')
            initial=pixels(frame)
            assert len(set(initial))>1
            shutil.copy2(frame,OUT/(key+'-initial.bmp'))
            mi.clear_stops();mi.command('-exec-continue');time.sleep(.1);press('PLUS');time.sleep(.3)
            mi.advance('-exec-interrupt')
            assert mi.value(value_expression)=='1'
            checked('Release binary responds to actual PLUS input')
        mi.command('-break-delete')
        mi.clear_stops();mi.command('-exec-continue');time.sleep(.35)
        mi.advance('-exec-interrupt')
        updated=pixels(frame)
        assert updated!=initial,'Screen did not reflect new counter value'
        status=ctrl({'command':'status'})
        assert status['state']=='paused' and not status.get('error'),status
        assert mi.value(value_expression)=='1' and mi.value(updates_expression)=='1'
        shutil.copy2(frame,OUT/(key+'-updated.bmp'))
        try:
            from PIL import Image
            Image.open(frame).save(OUT/(key+'-updated.png'))
        except ImportError:pass
        checked('updated screen differs from initial screen and emulator reports a clean paused state')
        mi.command('-target-detach')
        ctrl({'command':'quit'})
        return {'example':example,'configuration':profile,'checks':checks,'g1aBytes':manifest['g1aBytes'],'status':status}
    finally:
        if mi:
            mi.close();(OUT/(key+'-gdb-mi.log')).write_text('\n'.join(mi.log)+'\n',encoding='utf-8')
        if stream:stream.close()
        if control:control.close()
        if process.poll() is None:process.terminate()
        process.wait(timeout=5);stderr.close()

if __name__=='__main__':
    results=[]
    try:
        for example in ('counter-c','counter-cpp'):
            for profile in ('Debug','Release'):results.append(verify(example,profile))
    finally:(OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
