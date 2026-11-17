"""Functional SH7305 regressions; authored instructions, no firmware needed."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_probe import Session, fixture


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fx-hardware-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = Session(fixture(self.root/'test.g1a'), self.root)
        self.addCleanup(self.s.close)
        self.r = self.s.remote

    def execute(self, code, **regs):
        # P2 avoids self-modifying test harness cache effects.
        address = 0xa8030000
        data = bytes.fromhex(code)
        self.r.write(address, data + bytes.fromhex('affe0009'))
        end = address + len(data)
        self.r.request(f'Z0,{end:x},2')
        for k, v in regs.items(): self.r.set(int(k[1:]), v)
        self.r.set(16, address)
        stop = self.r.request('c')
        self.r.request(f'z0,{end:x},2')
        return stop

    def write(self, address, value):
        self.execute('2452', r4=address, r5=value)

    def read(self, address):
        self.execute('6042', r4=address)
        return self.r.get(0)

    def map(self, slot, va, pa, flags=0x17e):
        self.write(0xff000000, va)
        self.write(0xff000004, pa | flags)
        self.write(0xff000010, 0x00fc0101 | (slot << 10))
        self.execute('0038')

    def call(self, address):
        self.execute('440b0009', r4=address)
        return self.r.get(0)

    def test_instruction_cache_needs_icbi(self):
        a = 0x88040000
        self.r.write(a, bytes.fromhex('e011000b0009'))
        self.assertEqual(self.call(a), 0x11)
        self.write(a, 0xe022000b)
        self.assertEqual(self.read(a), 0xe022000b)
        self.assertEqual(self.call(a), 0x11)
        self.assertEqual(self.call(a | 0x20000000), 0x22)
        self.execute('00ab00e3', r0=a)
        self.assertEqual(self.call(a), 0x22)

    def test_ldtlb_leaves_itlb_stale(self):
        self.r.write(0x88040000, bytes.fromhex('e011000b0009'))
        self.r.write(0x88041000, bytes.fromhex('e022000b0009'))
        self.map(60, 0x12000000, 0x08040000)
        self.assertEqual(self.call(0x12000000), 0x11)
        self.map(60, 0x12000000, 0x08041000)
        self.assertEqual(self.read(0x12000000), 0xe022000b)
        self.assertEqual(self.call(0x12000000), 0x11)
        for i in range(4): self.write(0xf2000000 + (i << 8), 0)
        self.assertEqual(self.call(0x12000000), 0x22)

    def test_page_size_permissions_and_missing_mapping(self):
        self.r.write(0x88040400, bytes.fromhex('12345678'))
        self.map(60, 0x12000400, 0x08040400, 0x16e)  # 1 KiB
        self.assertEqual(self.read(0x12000400), 0x12345678)
        self.map(60, 0x12000400, 0x08040400, 0x14e)  # read-only
        self.write(0x12000400, 0xffffffff)
        self.assertEqual(self.s.command('status')['state'], 'error')
        self.assertEqual(self.r.read_memory(0x88040400,4), bytes.fromhex('12345678'))

    def test_unmapped_scratch_does_not_refill(self):
        self.read(0x12000000)
        self.assertEqual(self.s.command('status')['state'], 'error')

    def test_multiple_hit_is_error(self):
        self.map(60, 0x12000000, 0x08040000)
        self.map(61, 0x12000000, 0x08041000)
        self.read(0x12000000)
        self.assertEqual(self.s.command('status')['state'], 'error')

    def test_reserved_entries_survive_os_refill(self):
        self.map(60, 0x12000000, 0x08040000)
        self.write(0xff000010, (60 << 18) | 0x101)
        for n in range(80): self.read(0x08100000 + (n % 24) * 4096)
        self.assertEqual(self.read(0xf6003c00) & 0xfffffd00, 0x12000100)
        self.assertEqual((self.read(0xff000010) >> 18) & 63, 60)

    def test_unprotected_entry_is_evicted_on_os_refill(self):
        self.map(60,0x12000000,0x08040000)
        # Drop the initial OS RAM page, then force the next refill into slot 60.
        self.write(0xf6000200,0)
        self.write(0xff000010,0x00fc0101 | (60<<10))
        self.read(0x08100000)
        self.assertNotEqual(self.read(0xf6003c00)&0xfffffc00,0x12000000)
        self.read(0x12000000)
        self.assertEqual(self.s.command('status')['state'],'error')

    def test_injected_menu_is_a_returned_key(self):
        self.assertEqual(self.s.syscall(0x910,30003),1)
        self.s.syscall(0x90f,0x08102000)
        self.assertEqual(self.r.read_memory(0x08102000,4),(30003).to_bytes(4,'big'))
        self.assertFalse(self.s.command('status')['osMenu'])

    def test_version_fields_use_measured_bcd(self):
        self.s.syscall(0x15,0x08102000,0x08102001,0x08102002,0x08102004)
        self.assertEqual(self.r.read_memory(0x08102000,6),bytes.fromhex('037002000000'))
        self.assertEqual(self.r.read_memory(0x80010020,10),b'03.70.0200')

    def key_wait(self, menu, wait=True):
        # SH syscall arguments 5 and 6 are stack arguments.
        self.r.set(15,0x8807fff0)
        self.r.write(self.r.get(15), menu.to_bytes(4,'big')+bytes.fromhex('08102008'))
        return self.s.syscall(0x247,0x08102000,0x08102004,0,1,wait=wait)

    def test_matrix_menu_getkeywait_resumes_and_replaces(self):
        self.assertEqual(self.s.syscall(0x248,4,9,0),0)
        self.key_wait(0,wait=False)
        self.wait_menu()
        self.assertTrue(self.s.command('menu-resume')['ok'])
        time.sleep(.05)
        # Selecting the same icon resumes this wait; it is not a new launch
        # and the selection key must not be delivered to the application.
        self.assertFalse(self.s.command('status')['osMenu'])
        self.assertEqual(self.s.command('status')['pc'],'80010070')
        self.assertEqual(self.r.read_memory(0x08102000,8),bytes(8))
        self.press('EXE'); self.r.receive()
        self.assertEqual(self.r.read_memory(0x08102000,8),bytes.fromhex('0000000300000002'))
        self.s.syscall(0x248,4,9,0)
        self.key_wait(0,wait=False); self.wait_menu()
        self.assertTrue(self.s.command('menu-replace')['ok'])
        self.r.receive()
        self.assertEqual(self.s.command('status')['state'],'exited')

    def test_matrix_menu_disabled_returns_coordinates(self):
        self.s.syscall(0x248,4,9,0)
        self.assertEqual(self.key_wait(1),1)
        self.assertFalse(self.s.command('status')['osMenu'])
        self.assertEqual(self.r.read_memory(0x08102000,8),bytes.fromhex('0000000400000009'))

    def test_clear_buffer_discards_injected_events(self):
        self.s.syscall(0x910,30003)
        self.s.syscall(0x248,4,9,0)
        self.s.syscall(0x241)
        self.s.syscall(0x910,30004)
        self.s.syscall(0x90f,0x08102000)
        self.assertEqual(self.r.read_memory(0x08102000,4),(30004).to_bytes(4,'big'))
        self.assertFalse(self.s.command('status')['osMenu'])

    def test_quit_callback_once(self):
        # callback: increment *r1, with literal pointer stored after instructions.
        self.r.write(0x88040000, bytes.fromhex('d103601270012102000b00090009000988041000'))
        self.r.write(0x88041000, bytes(4))
        self.s.syscall(0x494, 0xa8040000)
        self.r.set(16, 0xdead0000)  # EXIT_ADDR from pinned upstream mem.h
        self.r.request('c')
        self.assertEqual(self.s.command('status')['state'], 'exited')
        self.assertEqual(self.r.read_memory(0x88041000,4), bytes.fromhex('00000001'))

    def press(self, key):
        self.assertTrue(self.s.command('key',key=key,down=True)['ok'])
        time.sleep(.03)
        self.s.command('key',key=key,down=False)

    def wait_menu(self):
        deadline = time.monotonic()+2
        while time.monotonic()<deadline:
            if self.s.command('status').get('osMenu'): return
            time.sleep(.01)
        self.fail('MENU did not suspend GetKey')

    def test_menu_resume_and_replace_callback(self):
        self.r.write(0x88040000, bytes.fromhex('d103601270012102000b00090009000988041000'))
        self.r.write(0x88041000, bytes(4))
        self.s.syscall(0x494,0xa8040000)
        self.s.syscall(0x90f,0x08102000,wait=False)
        self.press('MENU'); self.wait_menu()
        self.assertTrue(self.s.command('menu-resume')['ok'])
        self.press('EXE'); self.r.receive()
        self.assertEqual(self.r.read_memory(0x88041000,4),bytes(4))
        self.s.syscall(0x90f,0x08102000,wait=False)
        self.press('MENU'); self.wait_menu()
        self.assertTrue(self.s.command('menu-replace')['ok'])
        self.r.receive()
        self.assertEqual(self.s.command('status')['state'],'exited')
        self.assertEqual(self.r.read_memory(0x88041000,4),bytes.fromhex('00000001'))

    def test_timer_respects_interrupt_mask(self):
        self.r.write(0x88040000, bytes.fromhex('d103601270012102000b00090009000988041000'))
        self.r.write(0x88041000, bytes(4))
        timer=self.s.syscall(0x118,0,0xa8040000,80)
        self.assertGreater(timer,0)
        self.s.syscall(0x11a,timer)
        original=self.r.get(22)
        self.r.set(22,original|0xf0)
        self.s.syscall(0x420,240)
        self.assertEqual(self.r.read_memory(0x88041000,4),bytes(4))
        self.r.set(22,original & ~0xf0)
        self.s.syscall(0x420,240)
        self.assertGreater(int.from_bytes(self.r.read_memory(0x88041000,4),'big'),0)
        self.s.syscall(0x11b,timer); self.s.syscall(0x119,timer)

    def test_hardware_report_image_allocations_are_rejected_in_small_heap(self):
        # The reports prove these requests failed, not an exact heap capacity.
        with Session(fixture(self.root/'small.g1a'),self.root/'small',
                     ['--memory-profile','probe3']) as s:
            context=s.syscall(0xacd,0xbdc)
            self.assertNotEqual(context,0)
            for required in (0x12fff,0x20fff):
                self.assertEqual(s.syscall(0xacd,required),0)
            s.syscall(0xacc,context)
            self.assertEqual(s.syscall(0xacd,0xbdc),context)

    def test_menu_vram_stress_redraws_on_resume_without_unblocking_wait(self):
        with Session(fixture(self.root/'redraw.g1a'),self.root/'redraw',
                     ['--menu-vram-stress']) as s:
            s.syscall(0x143);s.syscall(0x28)
            before=(self.root/'redraw/screen.bmp').read_bytes()
            vram=s.syscall(0x135)
            s.remote.write(vram,bytes([255])*1024)
            s.syscall(0x248,4,9,0)
            s.remote.set(15,0x8807fff0)
            s.remote.write(0x8807fff0,bytes.fromhex('0000000008102008'))
            s.syscall(0x247,0x08102000,0x08102004,0,1,wait=False)
            deadline=time.monotonic()+2
            while not s.command('status')['osMenu'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(s.command('menu-resume')['ok'])
            time.sleep(.1)
            self.assertEqual(s.command('status')['pc'],'80010070')
            self.assertNotEqual((self.root/'redraw/screen.bmp').read_bytes(),before)
            s.command('key',key='EXE',down=True);s.remote.receive()


if __name__ == '__main__': unittest.main(verbosity=2)
