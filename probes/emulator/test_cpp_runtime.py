"""Build and execute the new C++17 vector/string/RAII probe on native SuperH."""
from pathlib import Path
import hashlib,json,os,shutil,socket,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_native_examples import MI,EMULATOR,GDB,ENV,pixels
ROOT=Path(__file__).resolve().parents[2]
SDK=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'.codex-build-envs/native-sdk-20261114/prefix'
PROJECT=ROOT/'probes/emulator/cpp-runtime'
OUT=ROOT/'probes/emulator/build/cpp-runtime'
OUT.mkdir(parents=True,exist_ok=True)
WORK=Path.home()/'.codex-build-envs/native-sdk-20261114/cpp-runtime-debug'
WORK.mkdir(parents=True,exist_ok=True)
result=subprocess.run([sys.executable,str(ROOT/'tooling/build-native.py'),str(SDK),str(PROJECT),str(OUT/'Debug'),'Debug'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
(OUT/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
if result.returncode:raise RuntimeError('C++ runtime build failed; see '+str(OUT/'build.log'))
manifest=json.loads((OUT/'Debug/artifact.json').read_text(encoding='utf-8'))
assert manifest['artifactPair']['verified']
for field in ('elf','g1a'):
    target=WORK/('probe.'+field)
    shutil.copy2(manifest[field],target)
    assert hashlib.sha256(target.read_bytes()).hexdigest()==manifest['sha256'][field]
cache=Path(manifest['cacheDirectory'])/'build'
shutil.copy2(cache/'cpp-runtime.map',OUT/'cpp-runtime.map')
shutil.copy2(cache/'.fxide-compiler-commands.jsonl',OUT/'compiler-commands.jsonl')
frame=WORK/'screen.bmp';frame.unlink(missing_ok=True)
errorlog=(OUT/'emulator.log').open('w',encoding='utf-8')
emulator=subprocess.Popen([str(EMULATOR),'--gdb-port','0','--control-port','0','--framebuffer',str(frame),str(WORK/'probe.g1a')],cwd=WORK,env=ENV,stdout=subprocess.PIPE,stderr=errorlog,text=True,encoding='utf-8')
mi=None;control=None;stream=None;values={}
try:
    ready=json.loads(emulator.stdout.readline())
    control=socket.create_connection(('127.0.0.1',ready['controlPort']),timeout=5);stream=control.makefile('rwb')
    def ctrl(command):
        stream.write((json.dumps(command)+'\n').encode());stream.flush()
        reply=json.loads(stream.readline());assert reply['ok'],reply;return reply
    mi=MI(WORK/'probe.elf',WORK)
    mi.command('-gdb-set pagination off');mi.command('-gdb-set confirm off');mi.command('-gdb-set mi-async on')
    mi.command('-gdb-set architecture sh4al-dsp');mi.command('-gdb-set endian big')
    mi.command('-target-select remote 127.0.0.1:'+str(ready['gdbPort']))
    mi.command('-break-insert runtime_complete')
    stop=mi.advance('-exec-continue')
    assert 'runtime_complete' in stop,stop
    for name,expected in (('runtime_result',328),('destructor_count',32),('completed_rounds',16),('heap_checks',63)):
        values[name]=int(mi.value(name),0);assert values[name]==expected,(name,values[name])
    for name in ('vector_buffer','string_buffer'):
        values[name]=int(mi.value(name),0);assert values[name]!=0
    assert values['vector_buffer']!=values['string_buffer']
    status=ctrl({'command':'status'});assert status['state']=='paused' and not status.get('error'),status
    assert len(set(pixels(frame)))>1
    shutil.copy2(frame,OUT/'runtime-screen.bmp')
    from PIL import Image
    Image.open(frame).save(OUT/'runtime-screen.png')
    mapping=(OUT/'cpp-runtime.map').read_text(encoding='utf-8',errors='replace')
    assert 'libstdc++.a' in mapping and ('new_op.o' in mapping or '_Znwj' in mapping or '_Znwm' in mapping), 'No evidence of libstdc++ allocation runtime linked'
    evidence={'passed':True,'language':'C++17','configuration':'Debug','exceptions':False,'threads':False,'values':values,'g1aBytes':manifest['g1aBytes'],'sha256':manifest['sha256'],'artifactPair':manifest['artifactPair'],'status':status}
    (OUT/'results.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,indent=2))
    mi.command('-target-detach');ctrl({'command':'quit'})
finally:
    if mi:
        mi.close();(OUT/'gdb-mi.log').write_text('\n'.join(mi.log)+'\n',encoding='utf-8')
    if stream:stream.close()
    if control:control.close()
    if emulator.poll() is None:emulator.terminate()
    emulator.wait(timeout=5);errorlog.close()
