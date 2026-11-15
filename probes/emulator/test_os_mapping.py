"""Firmware-derived HLE checks; optional raw OS is supplied locally, never bundled."""
import os,struct,subprocess,tempfile,unittest
from pathlib import Path
from runtime_probe import Session,fixture,DEFAULT_EXE
FIRMWARE=os.environ.get('FX_TEST_FIRMWARE')

class IdleContainer(unittest.TestCase):
 def test_device_handles_roundtrip_and_reject_wrong_namespace(self):
  with tempfile.TemporaryDirectory(prefix='fx-device-') as temp:
   root=Path(temp)
   for device in ('fls0','crd0'):
    (root/'storage'/device).mkdir(parents=True);(root/'storage'/device/'a.bin').write_bytes(b'....')
   with Session(fixture(root/'a.g1a'),root/'run',cwd=root) as s:
    for device,tag in [('fls0',1),('crd0',2)]:
     s.remote.write(0x88030000,('\\\\'+device+'\\a.bin\0').encode('utf-16be'))
     fd=s.syscall(0x42c,0x88030000,3,0);self.assertEqual(fd,tag<<24)
     self.assertEqual(s.syscall(0x42f,(3-tag)<<24),0xfffffffe)
     s.remote.write(0x88030100,b'ABCD');self.assertEqual(s.syscall(0x435,fd,0x88030100,4),4)
     self.assertEqual(s.syscall(0x432,fd,0x88030200,4,0),4)
     self.assertEqual(s.remote.read_memory(0x88030200,4),b'ABCD')
     self.assertEqual(s.syscall(0x42d,fd),0)
     self.assertEqual(s.syscall(0x42f,fd),0xfffffffe)
     self.assertEqual((root/'storage'/device/'a.bin').read_bytes(),b'ABCD')
 def test_probe_profile_copies_match(self):
  probes=Path(__file__).resolve().parent.parent
  for name in ('os-map-profile.h','os-map-hashes.h'):
   self.assertEqual((probes/name).read_bytes(),(probes/'file-map-probe/src'/name).read_bytes())
 def test_idle_close_does_not_close_bfile(self):
  with tempfile.TemporaryDirectory(prefix='fx-slot-') as temp:
   root=Path(temp);(root/'storage/fls0').mkdir(parents=True);(root/'storage/fls0/a.bin').write_bytes(b'abcd')
   with Session(fixture(root/'a.g1a'),root/'run',cwd=root) as s:
    name='\\\\fls0\\a.bin\0'.encode('utf-16be');s.remote.write(0x88030000,name)
    fd=s.syscall(0x42c,0x88030000,1,0)
    self.assertEqual(fd,0x01000000)
    self.assertEqual(s.syscall(0x42f,0),0xfffffffe)
    self.assertEqual(s.syscall(0x42f,0x02000000),0xfffffffe)
    for i in range(4):self.assertEqual(s.syscall(0x1e7,i),0xffffffff)
    for i in (0,1,2,3,4,0xffffffff):self.assertEqual(s.syscall(0x218,i),0xfffffffe)
    self.assertEqual(s.syscall(0x42f,fd),4)
    self.assertEqual(s.syscall(0x42d,fd),0)
 def test_strict_mode_rejects_partial_container_support(self):
  with tempfile.TemporaryDirectory(prefix='fx-slot-') as temp:
   root=Path(temp)
   with Session(fixture(root/'a.g1a'),root/'run',['--strict-stubs'],cwd=root) as s:
    s.syscall(0x1e7,0);self.assertEqual(s.command('status')['state'],'error')

@unittest.skipUnless(FIRMWARE,'set FX_TEST_FIRMWARE to a local extracted OS image')
class FirmwareMapping(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='fx-osmap-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.rom=Path(FIRMWARE).read_bytes()
  def word(a):return int.from_bytes(self.rom[a&0x1fffffff:(a&0x1fffffff)+4],'big')
  def lit(pc):
   off=pc&0x1fffffff;op=int.from_bytes(self.rom[off:off+2],'big');return word(((pc+4)&~3)+(op&255)*4)
  self.table=word(0x8001007c);self.refill=word(self.table+12);self.map=word(self.table+0x44)
  self.open_file=word(self.table+0x42c*4)
  self.close_search=word(self.table+0x218*4);self.search_slots=lit(self.close_search+0x1c)
  self.pages=lit(self.refill+0x28);self.cursor=self.pages+2048;self.query=lit(self.map+0x1c0)
  close=word(self.table+0x79c);self.close=close;self.slots=lit(close+16)
  op=int.from_bytes(self.rom[(close&0x1fffffff)+4:(close&0x1fffffff)+6],'big');disp=op&4095;disp=disp-4096 if disp&2048 else disp
  self.desc=lit(close+8+disp*2+12)
  self.s=Session(fixture(self.root/'test.g1a'),self.root/'run',['--os-firmware',FIRMWARE,'--file-map-stress'],cwd=self.root)
  self.addCleanup(self.s.close);self.r=self.s.remote
 def execute(self,code,**regs):
  address=0xa8030000;data=bytes.fromhex(code);self.r.write(address,data+bytes.fromhex('affe0009'));end=address+len(data)
  self.r.request(f'Z0,{end:x},2')
  for name,v in regs.items():self.r.set(int(name[1:]),v)
  self.r.set(16,address);self.r.request('c');self.r.request(f'z0,{end:x},2');return self.r.get(0)
 def read(self,a):return self.execute('6042',r4=a)
 def write(self,a,v):self.execute('2452',r4=a,r5=v)
 def get(self,a):return int.from_bytes(self.r.read_memory(a,4),'big')
 def test_refill_matches_actual_firmware_instructions(self):
  va=0x401234;pa=0x08042000;slot=54
  self.r.write(self.pages+((va-0x300000)>>12)*4,pa.to_bytes(4,'big'));self.r.write(self.cursor,slot.to_bytes(4,'big'))
  self.r.write(0x88042234,bytes.fromhex('12345678'))
  self.write(0xff000000,va);self.execute('440b0009',r4=self.refill)
  real=(self.read(0xf6000000+slot*256),self.read(0xf7000000+slot*256),self.get(self.cursor))
  self.write(0xf6000000+slot*256,0);self.r.write(self.cursor,slot.to_bytes(4,'big'))
  self.assertEqual(self.read(va),0x12345678)
  modeled=(self.read(0xf6000000+slot*256),self.read(0xf7000000+slot*256),self.get(self.cursor))
  self.assertEqual(real,modeled);self.assertEqual(real[2],0)
 def test_zero_entry_does_not_fall_back_to_host_image(self):
  self.r.write(self.pages,b'\0'*4);self.read(0x300000)
  self.assertEqual(self.s.command('status')['state'],'error')
 def test_window_end_is_diagnosed(self):
  self.r.write(self.cursor,(7).to_bytes(4,'big'));self.read(0x500000)
  self.assertEqual(self.s.command('status')['state'],'error')
 def test_slot_clean_and_dirty_states(self):
  self.r.write(self.slots,(0x12345678).to_bytes(4,'big')+b'\0');self.r.write(self.desc,b'\0\x01\0\0'+b'\0'*4)
  self.assertEqual(self.s.syscall(0x1e7,0),0);self.assertEqual(self.get(self.slots),0xffffffff)
  self.assertEqual(self.r.read_memory(self.slots+4,1),b'\xff')
  self.r.write(self.desc+4,(0x81200000).to_bytes(4,'big'));self.s.syscall(0x1e7,0)
  self.assertEqual(self.s.command('status')['state'],'error')
  self.assertIn('dirty container',self.s.command('status')['error'])
 def test_slot_idle_and_clean_match_firmware(self):
  for idle in (True,False):
   original=(0x12345678).to_bytes(4,'big')+bytes([255 if idle else 0])
   self.r.write(self.desc,b'\0\x01\0\0'+b'\0'*4);self.r.write(self.slots,original)
   value=self.execute('470b0009',r4=0,r7=self.close)
   observed=(value,self.r.read_memory(self.slots,5))
   self.r.write(self.slots,original)
   modeled=(self.s.syscall(0x1e7,0),self.r.read_memory(self.slots,5))
   self.assertEqual(observed,modeled)
 def test_search_close_matches_firmware_and_preserves_payload(self):
  for slot in (0,3,4,0xffffffff):
   for marker in (0x0ffe,0,0x0fff,0xffff):
    original=marker.to_bytes(2,'big')+bytes(range(2,36))
    at=self.search_slots+(slot if slot<4 else 0)*36
    self.r.write(at,original)
    actual=self.execute('470b0009',r4=slot,r7=self.close_search)
    observed=(actual,self.r.read_memory(at,36))
    self.r.write(at,original)
    modeled=(self.s.syscall(0x218,slot),self.r.read_memory(at,36))
    self.assertEqual(observed,modeled)
    self.assertEqual(modeled[0],0xfffffffe if slot>=4 or marker==0x0ffe else 0)
 def test_storage_device_tag_matches_firmware_instructions(self):
  # Execute the actual fls0 success block through its branch delay slot,
  # stopping before the enclosing routine's stack unwinding epilogue.
  for index in (0,3,0x1234):
   end=self.open_file+0xce
   self.r.request(f'Z0,{end:x},2');self.r.set(14,index);self.r.set(16,self.open_file+0x64)
   self.r.request('c');self.r.request(f'z0,{end:x},2')
   self.assertEqual(self.r.get(14),0x01000000|index)
 def test_fragment_addresses_and_write_rebuild(self):
  store=self.root/'storage/fls0';store.mkdir(parents=True,exist_ok=True);data=bytes((i*7)&255 for i in range(8193));(store/'pages.bin').write_bytes(data)
  self.r.write(0x88031000,'\\\\fls0\\pages.bin\0'.encode('utf-16be'));fd=self.s.syscall(0x42c,0x88031000,3,0)
  addresses=[]
  for offset in (0,1,4095,4096,8192):
   n=self.execute('470b0009',r4=fd,r5=offset,r6=0x88031100,r7=self.query);pa=self.get(0x88031100)
   self.assertEqual(n,4096-(offset&4095));self.assertEqual(self.r.read_memory(pa,1),data[offset:offset+1]);addresses.append(pa)
  self.assertEqual(addresses[3]-addresses[0],8192)
  original=self.get(self.pages);self.r.write(self.pages,(0x08040000).to_bytes(4,'big'))
  self.r.write(0x88031104,b'XY');self.assertEqual(self.s.syscall(0x435,fd,0x88031104,2),2)
  self.assertEqual(self.get(self.pages),original)
  self.assertEqual(self.execute('470b0009',r4=fd,r5=0,r6=0x88031100,r7=self.query),0xfffffffb)

if __name__=='__main__':unittest.main()
