"""Real Windows GDB integration; needs no ELF for the low-level checks."""
import subprocess, pathlib, json, socket
base=pathlib.Path(__file__).resolve().parent/'build'
err=(base/'gdb-emulator-stderr.log').open('w')
p=subprocess.Popen([str(base/'FxEmulator.exe'),'--fault-policy','pause','--gdb-port','0','--control-port','0','--framebuffer',str(base/'gdb-screen.bmp'),str(base/'cas02.g1a')],stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf8',cwd=base)
try:
    ready=json.loads(p.stdout.readline())
    # The fixture is rewritten after first execution. Use uncached P2 RAM;
    # real cached code requires ICBI after edits (tested by test_hardware.py).
    commands=['set pagination off','set confirm off','set architecture sh4al-dsp','set endian big',f'target remote 127.0.0.1:{ready["gdbPort"]}',
              'info registers r0 r15 pc pr sr','x/4i $pc','stepi','info registers pc','set $r0=42','print $r0',
              'set {unsigned int}0x08102000=1234','x/wx 0x08102000',
              'set {unsigned short}0xa8030000=0xe001','set {unsigned short}0xa8030002=0xe102',
              'set $pc=0xa8030000','break *0xa8030002','continue','info registers pc','delete breakpoints',
              'set {unsigned short}0xa8030000=0xe001','set {unsigned short}0xa8030002=0xe102',
              'set {unsigned short}0xa8030004=0x2202','set {unsigned short}0xa8030006=0x6322',
              'set {unsigned short}0xa8030008=0x7001','set {unsigned short}0xa803000a=0xaffb',
              'set {unsigned short}0xa803000c=0x0009','set $r2=0x08102000','set $pc=0xa8030000',
              'watch *(int*)0x08102000','continue','print *(int*)0x08102000','delete breakpoints',
              'rwatch *(int*)0x08102000','continue','print $r3','delete breakpoints',
              'break *0xa8030004 if $r0==3','continue','print $r0','delete breakpoints',
              'detach','quit']
    args=[r'C:\msys64\mingw64\bin\gdb-multiarch.exe','-nx','-batch']
    for command in commands:args+=['-ex',command]
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',timeout=30,cwd=base)
    (base/'gdb-real.log').write_text(result.stdout,encoding='utf8')
    print(result.stdout)
    if result.returncode:raise RuntimeError(result.returncode)
    assert '$1 = 42' in result.stdout
    assert '0x000004d2' in result.stdout
    assert 'Breakpoint 1,' in result.stdout
    assert 'Hardware watchpoint' in result.stdout and 'Hardware read watchpoint' in result.stdout
    assert '$4 = 3' in result.stdout
finally:
    if p.poll() is None:p.terminate();p.wait(timeout=5)
    err.close()
