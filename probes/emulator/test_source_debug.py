"""Historical CAS01 paired ELF/G1A source-debug integration (no WSL)."""
import subprocess, pathlib, json, socket, struct, hashlib, sys
sys.stdout.reconfigure(errors='backslashreplace')
base=pathlib.Path(__file__).resolve().parent/'build'
elf=(base/'cas-audit.elf').read_bytes();g1a=(base/'cas01.g1a').read_bytes()
h=struct.unpack('>16sHHIIIIIHHHHHH',elf[:52])
segments=[]
for i in range(h[10]):
    segment=struct.unpack('>IIIIIIII',elf[h[5]+i*h[9]:h[5]+i*h[9]+32])
    kind,offset,virtual,physical,size,memsize,flags,align=segment
    if kind==1 and size:
        start=physical-0x300000
        matches=elf[offset:offset+size]==g1a[start:start+size]
        segments.append({'physical':hex(physical),'fileBytes':size,'matches':matches})
        assert matches,segment
pair={'name':'CAS01 historical fixture','elfSha256':hashlib.sha256(elf).hexdigest(),'g1aSha256':hashlib.sha256(g1a).hexdigest(),'segments':segments,'totalLoadBytes':sum(s['fileBytes'] for s in segments),'payloadBytes':len(g1a)-512}
assert pair['totalLoadBytes']==pair['payloadBytes']
(base/'cas01-pairing.json').write_text(json.dumps(pair,indent=2))
err=(base/'source-emulator-stderr.log').open('w')
frame=base/'source-screen.bmp'
frame.unlink(missing_ok=True)
p=subprocess.Popen([str(base/'FxEmulator.exe'),'--gdb-port','0','--control-port','0','--framebuffer',str(base/'source-screen.bmp'),str(base/'cas01.g1a')],stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf8',cwd=base)
try:
    ready=json.loads(p.stdout.readline())
    commands=['set pagination off','set confirm off','set architecture sh4al-dsp','set endian big',
              'file cas-audit.elf','directory cas01-source/src',f'target remote 127.0.0.1:{ready["gdbPort"]}',
              'break main','continue','echo === MAIN LOCALS ===\n','print key_options','backtrace',
              'echo === SOURCE NEXT ===\n','next','info line','echo === UI BREAK ===\n','break ui_draw','continue',
              'info args','print ui->input[0]','print ui->notice','backtrace','echo === SOURCE NEXT AND STEP ===\n','next','step','backtrace',
              'delete breakpoints','echo === SOURCE FINISH ===\n','finish','backtrace','detach','quit']
    args=[r'C:\msys64\mingw64\bin\gdb-multiarch.exe','-nx','-batch']
    for command in commands:args+=['-ex',command]
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',timeout=30,cwd=base)
    (base/'gdb-source.log').write_text(result.stdout,encoding='utf8')
    print(result.stdout)
    assert result.returncode==0
    assert 'Breakpoint 1, main' in result.stdout
    assert 'Breakpoint 2.1, ui_draw' in result.stdout
    assert '#0  main' in result.stdout.split('=== SOURCE FINISH ===')[1]
    assert '$2 = 0' in result.stdout
    assert 'Starting CAS' in result.stdout
    assert frame.exists(), 'No fresh frame was published at the stopped source location'
    from PIL import Image
    image=Image.open(frame).convert('RGB')
    assert image.size==(128,64)
    assert any(sum(pixel)<300 for pixel in image.get_flattened_data()), 'Paused frame contains no rendered text'
    image.save(base/'source-paused.png')
finally:
    if p.poll() is None:p.terminate();p.wait(timeout=5)
    err.close()
