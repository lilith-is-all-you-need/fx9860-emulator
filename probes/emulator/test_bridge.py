"""Protocol/CPU integration checks against the real native emulator process."""
import json, socket, subprocess, time, pathlib, shutil, hashlib
base = pathlib.Path(__file__).resolve().parent
build = base / 'build'
report = {'checks': []}
def check(name, truth, evidence=None):
    report['checks'].append({'name':name, 'passed':bool(truth), 'evidence':evidence})
    if not truth: raise AssertionError(f'{name}: {evidence}')

class Remote:
    def __init__(self, port): self.s=socket.create_connection(('127.0.0.1',port),timeout=5);self.s.settimeout(10)
    def request(self,text,wait=True):
        b=text.encode();self.s.sendall(b'$'+b+b'#'+f'{sum(b)&255:02x}'.encode())
        if wait:return self.recv()
    def recv(self):
        while self.s.recv(1)!=b'$':pass
        out=b''
        while True:
            b=self.s.recv(1)
            if b==b'#':break
            out+=b
        expected=int(self.s.recv(2),16);assert expected==sum(out)&255
        self.s.sendall(b'+');return out.decode()
    def ctrlc(self):self.s.sendall(b'\x03');return self.recv()

runtime = build / '中文 空格路径'
runtime.mkdir(exist_ok=True)
shutil.copyfile(build/'cas02.g1a',runtime/'输入.g1a')
stderr=(build/'bridge-test-stderr.log').open('w',encoding='utf8')
process=subprocess.Popen([str(build/'FxEmulator.exe'),'--gdb-port','0','--control-port','0','--framebuffer',str(runtime/'显示.bmp'),str(runtime/'输入.g1a')],stdout=subprocess.PIPE,stderr=stderr,text=True,encoding='utf8',cwd=build)
try:
    ready=json.loads(process.stdout.readline());report['ready']=ready
    check('ready_loopback_dynamic_ports',ready['event']=='ready' and ready['gdbPort'] and ready['controlPort'])
    control=socket.create_connection(('127.0.0.1',ready['controlPort']),timeout=5);cf=control.makefile('rwb',buffering=0)
    def command(v):cf.write(json.dumps(v).encode()+b'\n');return json.loads(cf.readline())
    r=Remote(ready['gdbPort'])
    check('initial_pc',r.request('p10')=='00300200')
    before=command({'command':'status'});time.sleep(.1);after=command({'command':'status'})
    check('paused_time_frozen',before['cycles']==after['cycles']==0)
    check('register_packet_67_registers',len(r.request('g'))==67*8)
    for malformed in ['mffffffff,4','m8100000,2001','M8100000,1:gg','M8100000,2:ff',
                      'P10=1','Z0,300200,4','Z4,ffffffff,4','Pffff=0','m1', 'M1,1',
                      'Z0,1', 'pfffffffff']:
        check('reject_'+malformed,r.request(malformed).startswith('E'))
    r.s.sendall(b'$p10#00')
    check('bad_rsp_checksum_nack',r.s.recv(1)==b'-')
    for malformed in ['{"command":"status"}junk','{"command":"key","key":"EXE","down":trueXYZ}',
                      '{"command":"quit","command":"status"}', '{"command":"status",}',
                      '{"command":{"command":"quit"}}']:
        cf.write(malformed.encode()+b'\n')
        check('reject_bad_control_'+malformed,json.loads(cf.readline())['ok']==False)
    check('mmio_read_rejected',r.request('ma4050000,4')=='E14')
    check('unmapped_read_rejected',r.request('m50000000,4')=='E14')
    check('odd_breakpoint_rejected',r.request('Z0,300201,2')=='E22')
    check('step_executes',r.request('s').startswith('T05') and r.request('p10')!='00300200')
    # A real SH program in emulated RAM: loads, writes, reads, delayed branch.
    code='e001e102220263227001affb0009'
    check('write_code',r.request(f'M8101000,{len(code)//2:x}:{code}')=='OK')
    check('set_pc',r.request('P10=08101000')=='OK')
    check('set_r2',r.request('P2=08102000')=='OK')
    check('set_write_watch',r.request('Z2,8102000,4')=='OK')
    stop=r.request('c');check('write_watch_hits','watch:8102000;' in stop,stop)
    check('write_was_executed',r.request('m8102000,4')=='00000001')
    check('watch_stop_pc',r.request('p10')=='08101006')
    r.request('z2,8102000,4');r.request('Z3,8102000,4')
    stop=r.request('c');check('read_watch_hits','rwatch:8102000;' in stop,stop)
    check('read_register',r.request('p3')=='00000001')
    r.request('z3,8102000,4');r.request('Z0,810100c,2')
    stop=r.request('c');check('delay_slot_breakpoint',r.request('p10')=='0810100c',stop)
    check('delay_slot_pc_write_rejected',r.request('P10=08101000')=='E22')
    r.request('z0,810100c,2')
    r.request('s');check('delay_slot_resumes_target',r.request('p10')=='08101004')
    r.request('c',wait=False);time.sleep(.05);stop=r.ctrlc();check('async_interrupt',stop.startswith('T02'),stop)
    frozen=command({'command':'status'});time.sleep(.1);check('interrupt_freezes_time',frozen['cycles']==command({'command':'status'})['cycles'])
    check('control_unknown_key',command({'command':'key','key':'NOT_A_KEY','down':True})['ok']==False)
    check('control_key',command({'command':'key','key':'EXE','down':True})['ok'])
    command({'command':'quit'});process.wait(timeout=5)
    check('clean_quit',process.returncode==0)
finally:
    if process.poll() is None:process.kill();process.wait()
    stderr.close()
    (build/'bridge-test.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')

# A second fresh process exercises the actual G1A UI, rather than injected code.
process=subprocess.Popen([str(build/'FxEmulator.exe'),'--gdb-port','0','--control-port','0','--framebuffer',str(runtime/'显示.bmp'),str(runtime/'输入.g1a')],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',cwd=build)
try:
    ready=json.loads(process.stdout.readline())
    control=socket.create_connection(('127.0.0.1',ready['controlPort']),timeout=5);cf=control.makefile('rwb',buffering=0)
    r=Remote(ready['gdbPort']);r.request('c',wait=False)
    time.sleep(1)
    check('unicode_framebuffer_created',(runtime/'显示.bmp').exists())
    from PIL import Image
    initial=Image.open(runtime/'显示.bmp').copy();initial.save(build/'live-initial.png')
    check('native_framebuffer_128x64',initial.size==(128,64))
    for key in ['2','PLUS','2','EXE']:
        check('live_key_down_'+key,command({'command':'key','key':key,'down':True})['ok'])
        time.sleep(.12)
        check('live_key_up_'+key,command({'command':'key','key':key,'down':False})['ok'])
        time.sleep(.12)
    time.sleep(.3)
    r.ctrlc()
    actual=Image.open(runtime/'显示.bmp').copy();actual.save(build/'live-calculated.png')
    check('live_keys_change_pixels',initial.tobytes()!=actual.tobytes())
    # Compare the foreground masks, independent of RGB565 rounding.
    expected=Image.open(build/'calculated.png').convert('RGB').resize((128,64),Image.Resampling.NEAREST)
    mask=lambda im:[sum(p)<300 for p in im.convert('RGB').get_flattened_data()]
    check('live_g1a_result_matches_2_plus_2_equal_4',mask(actual)==mask(expected))
    command({'command':'quit'});process.wait(timeout=5)
finally:
    if process.poll() is None:process.kill();process.wait()
    (build/'bridge-test.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
print(f'{len(report["checks"])} native emulator checks passed')
