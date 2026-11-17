"""Guest-owned refill and precise register retry regression."""
import struct,tempfile,unittest
from pathlib import Path
import runtime_probe
class PreciseFaultTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='map698-cpu-');self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
  self.s=runtime_probe.Session(runtime_probe.fixture(root/'t.g1a'),root);self.addCleanup(self.s.close);self.r=self.s.remote
  # The authored guest handler writes one UTLB slot and RTEs. The host only
  # supplies test code/data, never a completed translation or return value.
  ops=[(0,0xf6000000),(1,0x00500100),0x2012,(0,0xf7000000),(1,0x0804017c),0x2012,0x002b,0x0009]
  data=bytearray(16);literals=bytearray()
  for i,op in enumerate(ops):
   if isinstance(op,tuple):
    reg,value=op;off=16+len(literals);disp=(off-((i*2+4)&~3))//4;word=0xd000|(reg<<8)|disp;literals+=struct.pack('>I',value)
   else:word=op
   struct.pack_into('>H',data,i*2,word)
  self.r.write(0xa8020400,data+literals);self.r.set(19,0xa8020000)
  self.r.write(0x88040000,bytes.fromhex('12345678'))
 def execute(self,hexcode,**regs):
  code=bytes.fromhex(hexcode);addr=0xa8030000;end=addr+len(code)
  self.r.write(addr,code+bytes.fromhex('affe0009'));self.r.request(f'Z0,{end:x},2')
  for reg,value in regs.items():self.r.set(int(reg[1:]),value)
  self.r.set(16,addr);self.r.request('c')
  self.assertEqual(self.s.command('status')['state'],'paused')
 def test_postincrement_read_retries_original_address(self):
  self.execute('6044',r4=0x500000)
  self.assertEqual(self.r.get(0),0x12);self.assertEqual(self.r.get(4),0x500001)
 def test_predecrement_store_retries_original_address(self):
  self.execute('2406',r4=0x500004,r0=0xabcdef01)
  self.assertEqual(self.r.get(4),0x500000);self.assertEqual(self.r.read_memory(0x88040000,4),bytes.fromhex('abcdef01'))
 def test_delay_slot_fault_retries_branch(self):
  self.execute('a0006044',r4=0x500000)
  self.assertEqual(self.r.get(0),0x12);self.assertEqual(self.r.get(4),0x500001)
 def test_guest_vector_calls_os_refill_for_latched_fault_page(self):
  # Authored gint-style vector: save PR, call FX syscall 3, restore PR, RTE.
  self.r.write(0xa8020400,bytes.fromhex('4f22d203420be0034f26002b0009000980010070'))
  self.execute('2402',r4=0xff000010,r0=0x00fc0105) # invalidate translations
  self.execute('6042',r4=0x300020)
  self.assertEqual(self.r.get(0),0x4050524f) # fixture header, not injected result
  self.assertEqual(self.r.get(4),0x300020)
  calls=self.s.command('syscalls')['recent']
  self.assertTrue(any(c['number']==3 and c['returned'] for c in calls))

if __name__=='__main__': unittest.main(verbosity=2)
