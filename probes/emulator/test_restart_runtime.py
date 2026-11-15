"""Check real gint restart machine code; the emulator has no actual OS menu."""
from pathlib import Path
import json, shutil, socket, subprocess, sys
from test_native_examples import MI, EMULATOR, ENV, pixels

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()/'.codex-build-envs/native-sdk-20261114/prefix'
OUT = ROOT/'probes/emulator/build/restart-runtime'
WORK = Path.home()/'.codex-build-envs/native-sdk-20261114/restart-runtime-debug'
OUT.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)
result = subprocess.run([sys.executable, str(ROOT/'tooling/build-native.py'), str(SDK),
    str(ROOT/'probes/emulator/restart-runtime'), str(OUT/'Debug'), 'Debug'],
    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
(OUT/'build.log').write_text(result.stdout+result.stderr, encoding='utf-8')
if result.returncode:
    raise RuntimeError('Restart build failed; inspect build.log')
manifest = json.loads((OUT/'Debug/artifact.json').read_text(encoding='utf-8'))
assert manifest['artifactPair']['verified']
for extension in ('elf', 'g1a'):
    shutil.copy2(manifest[extension], WORK/('probe.'+extension))
frame = WORK/'screen.bmp'
frame.unlink(missing_ok=True)
stderr = (OUT/'emulator.log').open('w', encoding='utf-8')
emulator = subprocess.Popen([str(EMULATOR), '--gdb-port', '0', '--control-port', '0',
    '--framebuffer', str(frame), str(WORK/'probe.g1a')], cwd=WORK, env=ENV,
    stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8')
mi = control = stream = None
try:
    ready = json.loads(emulator.stdout.readline())
    control = socket.create_connection(('127.0.0.1', ready['controlPort']), timeout=5)
    stream = control.makefile('rwb')
    def ctrl(command):
        stream.write((json.dumps(command)+'\n').encode()); stream.flush()
        reply = json.loads(stream.readline()); assert reply['ok'], reply
        return reply
    mi = MI(WORK/'probe.elf', WORK)
    mi.command('-gdb-set pagination off')
    mi.command('-gdb-set confirm off')
    mi.command('-gdb-set mi-async on')
    mi.command('-gdb-set architecture sh4al-dsp')
    mi.command('-gdb-set endian big')
    mi.command('-target-select remote 127.0.0.1:'+str(ready['gdbPort']))
    mi.command('-break-insert main')
    stops = []
    for index in range(4):
        stop = mi.advance('-exec-continue')
        assert 'func="main"' in stop, stop
        assert mi.value('initialized_value') == '42'
        assert mi.value('zero_value') == '0'
        status = ctrl({'command': 'status'})
        assert status['state'] == 'paused' and not status.get('error'), status
        stops.append({'mainEntry': index+1, 'initializedValue': 42, 'zeroValue': 0, 'status': status})
        if index:
            assert len(set(pixels(frame))) > 1
    shutil.copy2(frame, OUT/'restart-screen.bmp')
    evidence = {'passed': True, 'checks': stops, 'sha256': manifest['sha256'],
        'artifactPair': manifest['artifactPair'],
        'limitation': 'DisplayMainMenu is a no-op; return from main immediately re-enters the add-in. This is not a real OS menu or hardware reentry test.'}
    (OUT/'results.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2))
    mi.command('-target-detach'); ctrl({'command': 'quit'})
finally:
    if mi:
        mi.close(); (OUT/'gdb-mi.log').write_text('\n'.join(mi.log)+'\n', encoding='utf-8')
    if stream: stream.close()
    if control: control.close()
    if emulator.poll() is None: emulator.terminate()
    emulator.wait(timeout=5); stderr.close()
