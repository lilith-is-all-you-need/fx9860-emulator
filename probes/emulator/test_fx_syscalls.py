"""FX ABI tests: guest buffers, real dispatch, negative/alias/boundary cases."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_probe import Session, fixture


class FxSyscalls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fx-syscalls-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = Session(fixture(self.root/'test.g1a'), self.root)
        self.addCleanup(self.s.close)
        self.r = self.s.remote
        self.p, self.q = 0xa8020000, 0x88021000

    def test_os_version_string_aliases_boundaries_and_numeric_agreement(self):
        for destination in [self.p, self.q, 0x08100ffa, 0x8807fff5]:
            with self.subTest(destination=hex(destination)):
                self.r.write(destination-1, b'X'*12)
                if destination != 0x8807fff5:
                    self.r.write(destination+11, b'Y')
                self.s.syscall(0x2ee, destination)
                self.assertEqual(self.s.command('status')['state'], 'paused')
                self.assertEqual(self.r.read_memory(destination-1,12), b'X03.70.0200\0')
                if destination != 0x8807fff5:
                    self.assertEqual(self.r.read_memory(destination+11,1), b'Y')
        self.assertEqual(self.r.read_memory(self.p,11), self.r.read_memory(0x88020000,11))
        self.s.syscall(0x15, self.q+32, self.q+33, self.q+34, self.q+36)
        self.assertEqual(self.r.read_memory(self.q+32,6), bytes.fromhex('037002000000'))
        version_calls = [c for c in self.s.command('syscalls')['recent'] if c['number']==0x2ee]
        self.assertTrue(version_calls)
        self.assertTrue(all(c['kind']=='implemented' and c['returned'] for c in version_calls))

    def test_sdk_graph_clipping_stride_and_independent_destinations(self):
        # 9-pixel rows, clipped one pixel at the left: 010101011 / 101010100.
        self.r.write(self.q,bytes.fromhex('5580aa00'))
        self.r.write(self.p,struct.pack('>iiIII2B',-1,2,9,2,self.q,1,1))
        for n in [0x1c,0x1d,0x1e]:
            self.s.syscall(0x144)
            self.s.syscall(n,self.p)
            self.s.syscall(0x145,self.p+32)
            self.s.syscall(0x024,self.p+32+1024)
            expected=bytearray(1024);expected[32]=0xab;expected[48]=0x54
            self.assertEqual(self.r.read_memory(self.p+32,1024),bytes(expected) if n!=0x1d else bytes(1024))
            self.assertEqual(self.r.read_memory(self.p+32+1024,1024),bytes(expected) if n!=0x1c else bytes(1024))

    def test_sdk_graph_unsupported_mode_fails_explicitly(self):
        self.r.write(self.p,struct.pack('>iiIII2B',0,0,8,1,self.q,99,1))
        self.s.syscall(0x1e,self.p)
        self.assertEqual(self.s.command('status')['state'],'error')
        self.assertIn('unsupported mode',self.s.command('status')['error'])

    def test_os_version_invalid_span_does_not_partially_write(self):
        # The last ten bytes fit, but the mandatory NUL would be outside RAM.
        self.r.write(0x8807fff6, b'X'*10)
        self.s.syscall(0x2ee, 0x8807fff6)
        self.assertEqual(self.s.command('status')['state'], 'error')
        self.assertEqual(self.r.read_memory(0x8807fff6,10), b'X'*10)

    def test_os_version_bad_destination_faults(self):
        for address in [0, 0xfffffff8, 0xa4150000, 0x00300200]:
            with self.subTest(address=hex(address)), Session(
                    self.root/'test.g1a', self.root/f'bad-destination-{address:x}') as s:
                s.syscall(0x2ee, address)
                self.assertEqual(s.command('status')['state'], 'error')

    def test_filename_padding_terminators_and_low_bytes(self):
        for suffix, padding in [(b'\0', b'\0\0'), (b'\xff', b'\xff\xff')]:
            self.r.write(self.p, b'Ab'+suffix+b'garbage')
            self.r.write(self.q, b'x'*16)
            self.s.syscall(0x457, self.q, self.p, 5)
            self.assertEqual(self.r.read_memory(self.q, 12), b'\0A\0b'+padding*3+b'xx')
            self.assertEqual(self.s.syscall(0x450, self.q), 2)
            self.s.syscall(0x456, self.p, self.q, 5)
            self.assertEqual(self.r.read_memory(self.p, 5), b'Ab'+suffix*3)
        self.r.write(self.q, bytes.fromhex('12340000'))
        self.s.syscall(0x456, self.p, self.q, 3)
        self.assertEqual(self.r.read_memory(self.p, 3), b'4\0\0')
        self.s.syscall(0x457, self.q, 0xdead0000, 0)
        self.assertEqual(self.s.command('status')['state'], 'paused')

    def test_filename_count_overflow_and_unmapped_destination(self):
        self.r.write(self.p, b'A\0')
        self.r.write(0x8807fffc, b'XXXX')
        self.s.syscall(0x457, 0x8807fffc, self.p, 4)
        self.assertEqual(self.s.command('status')['state'], 'error')
        self.assertEqual(self.r.read_memory(0x8807fffc, 4), b'XXXX')

    def test_device_ids(self):
        for name, expected in [('fls0',1),('\\\\fls0\\a.bin',1),('crd0',2),('xxx0',0xffffffff),('fls',0xffffffff)]:
            self.r.write(self.p, name.encode('utf-16-be')+b'\0\0')
            self.assertEqual(self.s.syscall(0x429, self.p), expected)

    def test_fx_hex_return_codes_and_invalid_input(self):
        for n,text,expected,size in [(0x2a1,b'aF',0xaf,1),(0x2a2,b'12fE',0x12fe,2)]:
            self.r.write(self.p,text)
            self.assertEqual(self.s.syscall(n,self.p,self.q),1)
            self.assertEqual(int.from_bytes(self.r.read_memory(self.q,size),'big'),expected)
            self.r.write(self.p,b'Z123');self.r.write(self.q,b'XX')
            self.assertEqual(self.s.syscall(n,self.p,self.q),0xffffffff)
            self.assertEqual(self.r.read_memory(self.q,2),b'XX')
        self.s.syscall(0x2a7,ord('G'),self.q)
        self.assertEqual(self.r.read_memory(self.q,1),b'\xff')
        self.s.syscall(0x2a7,ord('b'),self.q)
        self.assertEqual(self.r.read_memory(self.q,1),b'\x0b')
        for n,v,want in [(0x2a3,0x1ab,b'AB'),(0x2a4,0x12cdef,b'CDEF'),(0x2a8,0x2b,b'B')]:
            self.r.write(self.q,b'xxxxxx');self.s.syscall(n,v,self.q)
            self.assertEqual(self.r.read_memory(self.q,len(want)+1),want+b'x')

    def test_hex_width_zero_and_termination(self):
        for n in [0x161,0x467]:
            for width,want in [(0,b''),(3,b'EEF'),(8,b'DEADBEEF')]:
                self.r.write(self.q,b'x'*12)
                self.s.syscall(n,0xdeadbeef,self.q,width)
                self.assertEqual(self.r.read_memory(self.q,len(want)+2),want+b'\0x')

    def test_atoi_case_and_invert(self):
        for text,expected in [(b' \t-2147483648tail',0x80000000),(b'+42x',42),(b'xx12',0)]:
            self.r.write(self.p,text+b'\0')
            self.assertEqual(self.s.syscall(0x15f,self.p),expected)
        self.r.write(self.p,b'AbC-9\0');self.r.write(self.q,b'aBc-9\0')
        self.assertEqual(self.s.syscall(0x172,self.p,self.q),0)
        self.assertEqual(self.s.syscall(0x173,self.p,self.q),0)
        self.s.syscall(0x162,self.p);self.assertEqual(self.r.read_memory(self.p,6),b'ABC-9\0')
        self.s.syscall(0x163,self.p);self.assertEqual(self.r.read_memory(self.p,6),b'abc-9\0')
        self.r.write(self.q,b'\0\x55\xaa\xffZ');self.s.syscall(0x18a,self.q,4)
        self.assertEqual(self.r.read_memory(self.q,5),b'\xff\xaa\x55\0Z')
        self.s.syscall(0x541,0x80000000,self.q)
        self.assertEqual(self.r.read_memory(self.q,12),b'-2147483648\0')

    def test_search_empty_nul_and_missing(self):
        self.r.write(self.p,b'ababc\0');self.r.write(self.q,b'abc\0')
        self.assertEqual(self.s.syscall(0xe6e,self.p,ord('b')),self.p+1)
        self.assertEqual(self.s.syscall(0xe6e,self.p,0),self.p+5)
        self.assertEqual(self.s.syscall(0xe6e,self.p,ord('z')),0)
        self.assertEqual(self.s.syscall(0xe6f,self.p,self.q),self.p+2)
        self.assertEqual(self.s.syscall(0xe6f,self.p,self.q+3),self.p)
        self.r.write(self.q,b'ababd\0');self.assertEqual(self.s.syscall(0xe6f,self.p,self.q),0)
        self.assertEqual(self.s.syscall(0x2a9,self.p),5)

    def test_multibyte_operations_and_source_return_quirk(self):
        text=b'\xf7D6U\xe5Z\0';self.r.write(self.p,text)
        self.assertEqual(self.s.syscall(0x533,self.p),4)
        self.assertEqual(self.s.syscall(0x534,self.p),6)
        self.assertEqual(self.s.syscall(0x53c,self.p),self.p+2)
        self.assertEqual(self.s.syscall(0x53d,self.p),0xf744)
        for c,yes in [(0x7f,1),(0xe5,1),(0xe7,1),(0xf7,1),(0xf9,1),(0x41,0),(0xe8,0)]:
            self.assertEqual(self.s.syscall(0x531,c),yes)
        self.assertEqual(self.s.syscall(0x538,self.q,self.p),self.q)
        self.assertEqual(self.r.read_memory(self.q,7),text)
        self.assertEqual(self.s.syscall(0x537,self.q,self.p,1),self.p)
        self.assertEqual(self.r.read_memory(self.q,8),text[:-1]+b'\xf7\0')
        self.r.write(self.q,b'A\0');self.s.syscall(0x536,self.q,self.p)
        self.assertEqual(self.r.read_memory(self.q,8),b'A'+text)
        copy=self.s.syscall(0x53e,self.p)
        self.assertNotEqual(copy,0);self.assertEqual(self.r.read_memory(copy,7),text)

    def test_cursor_state_partial_trace_and_off(self):
        self.s.syscall(0x138,20,7)
        self.assertEqual(self.s.syscall(0x139,0x12),1)
        self.assertEqual(self.s.syscall(0x80e),9)
        self.assertEqual(self.s.syscall(0x139,0x13),0)
        self.s.syscall(0x13a,2);self.assertEqual(self.s.syscall(0x13b,self.q),1)
        self.assertEqual(struct.unpack('>4I',self.r.read_memory(self.q,16)),(20,7,0x12,1))
        self.s.syscall(0x811,9);self.assertEqual(self.s.syscall(0x80e),9)
        self.s.syscall(0x80f,self.q)
        self.assertEqual(struct.unpack('>4I',self.r.read_memory(self.q,16)),(9,21,8,0))
        self.s.syscall(0x812);self.s.syscall(0x80f,self.q)
        self.assertEqual(self.r.read_memory(self.q,4),b'\xff'*4)
        self.assertGreater(self.s.command('syscalls')['partial'],0)

    def test_faulting_string_and_untrusted_length_terminate(self):
        self.r.write(0x8807fffe,b'xx')
        self.s.syscall(0xe6e,0x8807fffe,ord('z'))
        self.assertEqual(self.s.command('status')['state'],'error')


if __name__=='__main__': unittest.main()
