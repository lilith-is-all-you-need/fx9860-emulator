"""Bounded native emulator sessions; only Python's standard library is needed.

CLI inputs remain external: no third-party G1A is bundled in this repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import socket
import subprocess
import threading
import time

BASE = Path(__file__).resolve().parent
DEFAULT_EXE = BASE / 'FxEmulator.exe' if (BASE / 'FxEmulator.exe').is_file() else BASE / 'build/FxEmulator.exe'


def fixture(path):
    """An authored SH infinite loop, with a minimal G1A container."""
    data = bytearray(512)
    data[:9] = bytes.fromhex('aaacbdaf90889a8d0c')
    data[0x20:0x28] = b'@PROBE00'
    data[0x1d4:0x1dc] = b'PROBE000'
    data += bytes.fromhex('affe0009')  # bra .; nop
    path.write_bytes(data)
    return path


class Remote:
    def __init__(self, port, timeout=10):
        self.socket = socket.create_connection(('127.0.0.1', port), timeout)

    def read(self, size):
        out = bytearray()
        while len(out) < size:
            part = self.socket.recv(size - len(out))
            if not part:
                raise EOFError('emulator disconnected')
            out.extend(part)
        return bytes(out)

    def receive(self):
        while self.read(1) != b'$':
            pass
        out = bytearray()
        while (part := self.read(1)) != b'#':
            out.extend(part)
        if int(self.read(2), 16) != sum(out) & 255:
            raise RuntimeError('invalid RSP checksum')
        self.socket.sendall(b'+')
        return out.decode('ascii')

    def request(self, command, wait=True):
        data = command.encode('ascii')
        self.socket.sendall(b'$' + data + b'#' + f'{sum(data) & 255:02x}'.encode())
        return self.receive() if wait else None

    def interrupt(self):
        self.socket.sendall(b'\x03')
        return self.receive()

    def set(self, register, value):
        result = self.request(f'P{register:x}={value:08x}')
        if result != 'OK':
            raise RuntimeError(f'register write: {result}')

    def get(self, register):
        return int(self.request(f'p{register:x}'), 16)

    def write(self, address, data):
        # RSP bridge intentionally limits a single transfer to 8 KiB.
        for offset in range(0, len(data), 4096):
            part = data[offset:offset + 4096]
            result = self.request(f'M{address+offset:x},{len(part):x}:{part.hex()}')
            if result != 'OK':
                raise RuntimeError(f'memory write: {result}')

    def read_memory(self, address, size):
        return b''.join(bytes.fromhex(self.request(f'm{address+o:x},{min(4096,size-o):x}'))
                        for o in range(0, size, 4096))


class Session:
    def __init__(self, addin, output, options=(), executable=None, timeout=10, fault_policy='pause', cwd=None):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.remote = self.control = self.stream = None
        self.stderr = (self.output / 'stderr.log').open('w', encoding='utf8')
        self.process = subprocess.Popen([
            str(executable or DEFAULT_EXE), '--gdb-port', '0',
            '--control-port', '0', '--framebuffer', str(self.output / 'screen.bmp'),
            *(['--fault-policy', fault_policy] if fault_policy else []),
            *map(str, options), str(Path(addin).resolve())], stdout=subprocess.PIPE,
            stderr=self.stderr, text=True, encoding='utf8', cwd=cwd)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(self.process.stdout.readline()), daemon=True).start()
        try:
            self.ready = json.loads(ready.get(timeout=timeout))
            self.remote = Remote(self.ready['gdbPort'], timeout)
            self.control = socket.create_connection(('127.0.0.1', self.ready['controlPort']), timeout)
            self.stream = self.control.makefile('rwb', buffering=0)
        except BaseException:
            self.close()
            raise

    def command(self, command, **fields):
        self.stream.write(json.dumps({'command': command, **fields}).encode() + b'\n')
        return json.loads(self.stream.readline())

    def syscall(self, number, *args, wait=True):
        r = self.remote
        r.write(0x08101000, bytes.fromhex('affe0009'))
        r.request('Z0,8101000,2')
        for index, value in enumerate(args):
            r.set(4 + index, value)
        r.set(0, number)
        r.set(17, 0x08101000)
        r.set(16, 0x80010070)
        r.request('c', wait=wait)
        return r.get(0) if wait else None

    def close(self):
        if self.process.poll() is None and self.stream:
            try:
                self.command('quit')
                self.process.wait(timeout=3)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=3)
        if self.stream:
            self.stream.close()
        if self.control:
            self.control.close()
        if self.remote:
            self.remote.socket.close()
        self.process.stdout.close()
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('addin', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emulator', type=Path)
    parser.add_argument('--memory-profile', choices=('default', 'khicas'), default='default')
    parser.add_argument('--steps', type=int, default=2_000_000)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--strict-stubs', action='store_true')
    parser.add_argument('--heap-bytes', type=int)
    parser.add_argument('--keys', default='', help='Comma-separated key names, e.g. F1,2,PLUS,2,EXE')
    args = parser.parse_args()
    if args.steps <= 0 or args.timeout <= 0:
        parser.error('steps and timeout must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    options = ['--memory-profile', args.memory_profile, '--step-limit', args.steps,
               '--trace-syscalls', args.output.resolve() / 'syscalls.jsonl']
    if args.strict_stubs:
        options += ['--strict-stubs']
    if args.heap_bytes is not None:
        options += ['--heap-bytes', args.heap_bytes]
    with Session(args.addin, args.output, options, args.emulator, args.timeout) as session:
        session.remote.request('c', wait=False)
        key_events = []
        if args.keys:
            time.sleep(.4)
            for index, key in enumerate(args.keys.split(',')):
                key = key.strip()
                status = session.command('status')
                if status['state'] != 'running':
                    key_events.append({'key': key, 'skipped': status})
                    break
                screen = args.output / 'screen.bmp'
                if screen.exists():
                    (args.output / f'key-{index:03d}-before.bmp').write_bytes(screen.read_bytes())
                result = session.command('key', key=key, down=True)
                if not result['ok']:
                    raise ValueError(f'unknown key: {key}')
                time.sleep(.12)
                session.command('key', key=key, down=False)
                time.sleep(.2)
                key_events.append({'key': key, 'sent': True})
        try:
            stop = session.remote.receive()
        except TimeoutError:
            stop = session.remote.interrupt()
        report = {'inputSha256': hashlib.sha256(args.addin.read_bytes()).hexdigest(), 'keys': key_events,
                  'stop': stop, 'status': session.command('status'),
                  'diagnostics': session.command('diagnostics'),
                  'syscalls': session.command('syscalls')}
        (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
