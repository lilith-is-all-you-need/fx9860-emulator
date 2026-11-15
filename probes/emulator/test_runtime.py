"""Native HLE regression tests. Generates its own G1A; no SDK compiler needed."""
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import sys
import time
import unittest

# Also work with the portable SDK's isolated/embedded Python.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_probe import BASE, Session, fixture

MALLOC, FREE, CALLOC, REALLOC = 0xACD, 0xACC, 0xE6B, 0xE6D
MEMMOVE, MEMSET = 0xE6C, 0xAD0


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fx-runtime-中文 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addin = fixture(self.root / '输入.bin')

    def session(self, *options):
        session = Session(self.addin, self.root, options)
        self.addCleanup(session.close)
        return session

    def test_calloc_overflow_zero_and_reuse(self):
        s = self.session()
        p = s.syscall(CALLOC, 17, 2)
        self.assertEqual(p % 8, 0)
        self.assertNotEqual(p, 0)
        self.assertEqual(s.remote.read_memory(p, 34), bytes(34))
        s.remote.write(p, b'x' * 34)
        s.syscall(FREE, p)
        self.assertEqual(s.syscall(CALLOC, 17, 2), p)
        self.assertEqual(s.remote.read_memory(p, 34), bytes(34))
        for n, size in [(0, 99), (99, 0), (0x80000000, 2), (0xffffffff, 0xffffffff)]:
            self.assertEqual(s.syscall(CALLOC, n, size), 0)
        for size in [0, 0xffffffff, 0xfffffff8]:
            self.assertEqual(s.syscall(MALLOC, size), 0)
        self.assertEqual(s.command('status')['state'], 'paused')

    def test_realloc_and_oom_retains_original(self):
        s = self.session('--heap-bytes', '128')
        p = s.syscall(REALLOC, 0, 24)
        s.remote.write(p, b'x' * 24)
        q = s.syscall(REALLOC, p, 40)
        self.assertNotEqual(q, 0)
        self.assertEqual(s.remote.read_memory(q, 24), b'x' * 24)
        self.assertEqual(s.syscall(REALLOC, q, 4), q)
        self.assertEqual(s.syscall(REALLOC, q, 256), 0)
        self.assertEqual(s.remote.read_memory(q, 24), b'x' * 24)
        self.assertEqual(s.syscall(REALLOC, q, 0), 0)
        self.assertEqual(s.syscall(FREE, 0), 0)
        self.assertNotEqual(s.syscall(MALLOC, 120), 0)  # coalesced arena
        self.assertEqual(s.syscall(MALLOC, 1), 0)

    def test_allocator_fragmentation_randomized(self):
        s = self.session('--heap-bytes', '2048')
        rng, live = random.Random(9860), {}
        for i in range(160):
            if live and rng.randrange(3) == 0:
                p = rng.choice(list(live))
                self.assertEqual(s.remote.read_memory(p, len(live[p])), live.pop(p))
                s.syscall(FREE, p)
            else:
                size = rng.randrange(1, 129)
                p = s.syscall(MALLOC, size)
                if p:
                    self.assertEqual(p % 8, 0)
                    for q, data in live.items():
                        self.assertTrue(p + size <= q or q + len(data) <= p)
                    live[p] = bytes([i & 255]) * size
                    s.remote.write(p, live[p])
        for p, data in live.items():
            self.assertEqual(s.remote.read_memory(p, len(data)), data)
            s.syscall(FREE, p)
        self.assertNotEqual(s.syscall(MALLOC, 2040), 0)
        trace = s.command('syscalls')
        self.assertEqual(len(trace['recent']), 16)
        self.assertEqual(trace['recent'][-1]['id'], trace['total'])

    def test_invalid_frees_and_heap_corruption(self):
        for mode in ['interior', 'double', 'zero-size', 'wrap-size', 'unaligned-size', 'invalid-used']:
            with self.subTest(mode=mode), Session(self.addin, self.root, ['--heap-bytes', '128']) as s:
                p = s.syscall(MALLOC, 16)
                if mode == 'interior':
                    s.syscall(FREE, p + 4)
                elif mode == 'double':
                    s.syscall(FREE, p)
                    s.syscall(FREE, p)
                else:
                    value = {'zero-size': 0, 'wrap-size': 0xfffffff8,
                             'unaligned-size': 17, 'invalid-used': 2}[mode]
                    s.remote.write(p - (4 if mode == 'invalid-used' else 8), value.to_bytes(4, 'big'))
                    s.syscall(MALLOC, 8)
                status = s.command('status')
                self.assertEqual(status['state'], 'error')
                self.assertIn('HLE heap', status['error'])
                self.assertTrue(s.command('syscalls')['recent'][-1]['failed'])

    def test_memmove_overlap_and_uncached_alias(self):
        s = self.session()
        p = 0x88020000
        for destination, source in [(p+3, p), (p, p+3), (0xA8020003, p)]:
            s.remote.write(p, bytes(range(32)))
            expected = bytearray(range(32))
            offset = destination & 0x1fffffff
            offset -= p & 0x1fffffff
            start = source - p
            expected[offset:offset+16] = expected[start:start+16]
            self.assertEqual(s.syscall(MEMMOVE, destination, source, 16), destination)
            self.assertEqual(s.remote.read_memory(p, 32), expected)
        self.assertEqual(s.syscall(MEMMOVE, 0xffffffff, 0xffffffff, 0), 0xffffffff)
        self.assertEqual(s.syscall(MEMSET, 0xffffffff, 0, 0), 0xffffffff)

    def test_bulk_cross_page_and_watchpoint(self):
        s = self.session()
        p, q = 0x88020ff0, 0x88023ff0
        data = bytes(range(64))
        s.remote.write(p, data)
        self.assertEqual(s.remote.request(f'Z2,{q:x},4'), 'OK')
        s.syscall(MEMMOVE, q, p, 64)
        self.assertEqual(s.remote.read_memory(q, 64), data)
        self.assertEqual(s.command('status')['reason'], 'watchpoint')
        s.remote.request(f'z2,{q:x},4')
        s.syscall(MEMSET, q, 0x1234, 64)
        self.assertEqual(s.remote.read_memory(q, 64), b'4' * 64)

    def test_invalid_bulk_ranges_do_not_partially_write(self):
        for destination, source, size in [(0x8807fff0, 0x88020000, 32),
                (0x88020000, 0x50000000, 16), (0x80000200, 0x88020000, 4),
                (0xfffffff0, 0x88020000, 32), (0x88020000, 0, 0xffffffff)]:
            with self.subTest(destination=destination, size=size), Session(self.addin, self.root) as s:
                s.remote.write(0x8807fff0, b'X' * 16)
                s.remote.write(0x88020000, b'Y' * 32)
                s.syscall(MEMMOVE, destination, source, size)
                self.assertEqual(s.command('status')['state'], 'error')
                self.assertEqual(s.remote.read_memory(0x8807fff0, 16), b'X' * 16)
                self.assertEqual(s.remote.read_memory(0x88020000, 32), b'Y' * 32)

    def test_trace_and_strict_stubs(self):
        log = self.root / '系统调用.jsonl'
        s = self.session('--trace-syscalls', str(log))
        s.syscall(CALLOC, 17, 2)
        s.syscall(0x242, 0)  # key-repeat timing remains an explicit stub
        s.syscall(0xffff, 1, 2, 3, 4)
        trace = s.command('syscalls')
        self.assertEqual((trace['total'], trace['implemented'], trace['stubs'], trace['missing']), (3, 1, 1, 1))
        last = trace['recent'][-1]
        self.assertEqual(last['args'], [1, 2, 3, 4])
        self.assertEqual(last['caller'], '08101000')
        self.assertFalse(last['returned'])
        self.assertTrue(last['failed'])
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(records), 6)
        with Session(self.addin, self.root / 'strict', ['--strict-stubs']) as strict:
            strict.syscall(0x242, 0)
            self.assertEqual(strict.command('status')['state'], 'error')
            self.assertIn('strict mode', strict.command('status')['error'])

    def test_memory_profile_and_stack_guard(self):
        s = self.session('--memory-profile', 'khicas')
        d = s.command('diagnostics')
        self.assertEqual((d['heapBase'], d['heapBytes'], d['stackTop'], d['stackFloor']),
                         ('88040000', 49152, '88051000', '8804C000'))
        self.assertEqual(s.remote.get(15), 0x88051000)
        self.assertFalse(d['realMmu'])
        s.remote.set(15, 0x8804bffc)
        s.remote.request('c')
        self.assertEqual(s.command('status')['reason'], 'stack-range')
        self.assertEqual(s.command('diagnostics')['executedSteps'], 0)

    def test_probe3_heap_address_and_bounded_capacity(self):
        s = self.session('--memory-profile', 'probe3')
        d = s.command('diagnostics')
        self.assertEqual((d['heapBase'], d['heapBytes'], d['stackTop']),
                         ('88050298', 49152, '88050000'))
        p = s.syscall(MALLOC, 40800)
        self.assertEqual(p, 0x880502a0)
        self.assertLess(p+40800, 0x88060000)
        self.assertEqual(s.syscall(MALLOC, 10000), 0)

    def test_cursor_bounds_and_setup_scope(self):
        s = self.session()
        self.assertEqual(s.syscall(0x138, 20, 7), 1)
        s.syscall(0x13b, 0x08102000)
        self.assertEqual(s.remote.read_memory(0x08102000, 8), bytes.fromhex('0000001400000007'))
        for x, y in [(21, 7), (20, 8), (0xffffffff, 0)]:
            self.assertEqual(s.syscall(0x138, x, y), 0)
            s.syscall(0x13b, 0x08102000)
            self.assertEqual(s.remote.read_memory(0x08102000, 8), bytes.fromhex('0000001400000007'))
        self.assertEqual(s.syscall(0x4dc, 0x14), 0)
        s.syscall(0x4dc, 0x10014)
        self.assertIn('unsupported Setup_GetEntry', s.command('status')['error'])

    def test_blocking_getkey_trace_interrupt_and_alpha_lock(self):
        s = self.session('--step-limit', '100')
        s.syscall(0x90f, 0x08102000, wait=False)
        # A blocked HLE call consumes no SH step budget; host interruption works.
        time.sleep(.05)
        trace = s.command('syscalls')['recent'][-1]
        self.assertEqual(trace['name'], 'GetKey')
        self.assertFalse(trace['completed'])
        self.assertTrue(s.remote.interrupt().startswith('T02'))
        s.remote.request('c', wait=False)
        for key in ['SHIFT', 'ALPHA', '2']:
            self.assertTrue(s.command('key', key=key, down=True)['ok'])
            time.sleep(.03)
            s.command('key', key=key, down=False)
        self.assertTrue(s.remote.receive().startswith('T05'))
        self.assertEqual(s.syscall(0x4dc, 0x14), 0x84)
        self.assertTrue(s.command('syscalls')['recent'][-2]['completed'])

    def test_step_limit_resets_on_resume(self):
        s = self.session('--step-limit', '100')
        for expected in [100, 200]:
            self.assertTrue(s.remote.request('c').startswith('T02'))
            self.assertEqual(s.command('status')['reason'], 'step-limit')
            self.assertEqual(s.command('diagnostics')['executedSteps'], expected)

    def test_cli_rejects_invalid_options_and_input_overwrite(self):
        command = [str(BASE / 'build/FxEmulator.exe'), '--framebuffer', str(self.root / 'out.bmp'), str(self.addin)]
        invalid = [('--gdb-port', '65536'), ('--control-port', '-1'), ('--gdb-port', '12junk'),
                   ('--step-limit', '18446744073709551616'), ('--heap-bytes', '15'),
                   ('--heap-bytes', '17'), ('--heap-bytes', '262144'),
                   ('--memory-profile', 'invented'), ('--step-limit', '\n2'),
                   ('--trace-syscalls', str(self.addin)), ('--framebuffer', str(self.addin))]
        original = self.addin.read_bytes()
        alias = self.root / 'same-input-hardlink.bin'
        os.link(self.addin, alias)
        invalid += [('--trace-syscalls', str(alias))]
        for option in invalid:
            with self.subTest(option=option):
                result = subprocess.run(command + list(option), capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(self.addin.read_bytes(), original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
