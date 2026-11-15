"""Fault recovery must archive the old machine before changing its state."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from runtime_probe import Session, fixture


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fx-recovery-中文 ')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.addin=fixture(self.root/'test.bin')

    def session(self,policy='reboot'):
        s=Session(self.addin,self.root,fault_policy=None if policy=='reboot' else policy,cwd=self.root)
        self.addCleanup(s.close)
        return s

    def report(self,s,kind):
        rec=s.command('recovery')
        self.assertTrue(rec['saved'])
        path=Path(rec['report']);report=json.loads(path.read_text())
        self.assertEqual(report['kind'],kind)
        self.assertEqual(len(report['hardware']['utlb']),64)
        self.assertEqual(len(report['hardware']['itlb']),4)
        self.assertEqual(path.with_suffix('.ram.bin').stat().st_size,512*1024)
        self.assertTrue(path.with_suffix('.bmp').is_file())
        return path,report

    def test_unknown_call_reboots_archives_and_waits(self):
        s=self.session();s.remote.write(0x88060000,b'FAULTMARK')
        s.syscall(0xffff,11,22,33,44)
        self.assertEqual(s.command('status')['state'],'rebooted')
        path,r=self.report(s,'unexpected-fault')
        self.assertIn('0xFFFF',r['error'])
        self.assertEqual(r['registers']['pc'],0x80010070)
        self.assertEqual(r['syscalls']['recent'][-1]['args'],[11,22,33,44])
        self.assertEqual(path.with_suffix('.ram.bin').read_bytes()[0x60000:0x60009],b'FAULTMARK')
        self.assertEqual(s.remote.read_memory(0x88060000,9),bytes(9))
        self.assertEqual(s.remote.get(16),0x300200)
        time.sleep(.05);self.assertEqual(s.remote.get(16),0x300200)
        self.assertTrue(s.command('launch')['ok']);time.sleep(.05)
        self.assertEqual(s.command('status')['state'],'running')
        s.remote.interrupt()
        s.syscall(0xffff)
        second,_=self.report(s,'unexpected-fault')
        self.assertNotEqual(second,path);self.assertTrue(path.exists())
        self.assertEqual(s.command('recovery')['reboots'],2)

    def test_pause_retains_registers_and_ram_then_manual_reboot(self):
        s=self.session('pause');s.remote.write(0x88060000,b'KEEP');s.remote.set(8,0x12345678)
        s.syscall(0xffff)
        path,_=self.report(s,'unexpected-fault')
        self.assertEqual(s.command('status')['state'],'error')
        self.assertEqual(s.remote.get(8),0x12345678)
        self.assertEqual(s.remote.read_memory(0x88060000,4),b'KEEP')
        self.assertTrue(s.command('reboot')['ok']);s.remote.receive()
        self.assertEqual(s.command('status')['state'],'rebooted')
        self.assertEqual(s.command('recovery')['report'],str(path))

    def test_reset_syscall_is_explicit_and_does_not_call_quit_handler(self):
        s=self.session();s.syscall(0x494,0xdeadbeef)
        s.syscall(0x236)
        _,r=self.report(s,'syscall-0236')
        self.assertEqual(r['hardware']['quitHandler'],0xdeadbeef)
        self.assertEqual(s.command('status')['state'],'rebooted')

    def test_reset_vector_is_explicit_and_logged_before_fetch(self):
        s=self.session();s.remote.set(16,0xa0000000);s.remote.request('c')
        _,r=self.report(s,'reset-vector')
        self.assertEqual(r['registers']['pc'],0xa0000000)
        self.assertEqual(r['recentPC'][-1],0xa0000000)
        self.assertNotIn('illegal instruction',r['error'])

    def test_mmu_fault_keeps_bad_address(self):
        s=self.session();s.remote.write(0xa8030000,bytes.fromhex('6042affe0009'))
        s.remote.set(4,0x12000000);s.remote.set(16,0xa8030000);s.remote.request('c')
        _,r=self.report(s,'unexpected-fault')
        self.assertEqual(r['memoryFault']['address'],0x12000000)
        self.assertEqual(r['registers']['opPc'],0xa8030000)

    def test_illegal_instruction_and_callback_fault(self):
        for callback in [False,True]:
            with self.subTest(callback=callback):
                s=self.session();exit_address=s.remote.get(17);s.remote.write(0xa8030000,b'\xff\xff')
                if callback:
                    s.syscall(0x494,0xa8030000)
                    # rts to the emulator's authored exit trampoline.
                    s.remote.write(0xa8030100,bytes.fromhex('000b0009'))
                    s.remote.set(17,exit_address);s.remote.set(16,0xa8030100)
                else:s.remote.set(16,0xa8030000)
                s.remote.request('c');_,r=self.report(s,'unexpected-fault')
                self.assertIn('illegal',r['error'])
                self.assertEqual(s.command('status')['state'],'rebooted')
                s.close()

    def test_report_failure_keeps_fault_in_memory(self):
        s=self.session();s.remote.write(0x88060000,b'KEEP')
        # Prevent the framebuffer archive from being created, after ready.
        (self.root/'screen.bmp').mkdir()
        s.syscall(0xffff)
        self.assertEqual(s.command('status')['reason'],'report-failed')
        self.assertEqual(s.command('recovery')['reboots'],0)
        self.assertEqual(s.remote.read_memory(0x88060000,4),b'KEEP')

    def test_manual_reboot_unwinds_blocking_getkey(self):
        s=self.session('pause');s.syscall(0x90f,0x08102000,wait=False)
        time.sleep(.03);s.remote.interrupt()
        self.assertTrue(s.command('reboot')['ok']);s.remote.receive()
        self.assertEqual(s.command('status')['state'],'rebooted')
        self.report(s,'debugger-reboot')

    def test_normal_return_does_not_reboot(self):
        s=self.session();s.remote.write(0xa8030000,bytes.fromhex('000b0009'))
        s.remote.set(16,0xa8030000);s.remote.request('c')
        self.assertEqual(s.command('status')['state'],'exited')
        self.assertFalse(s.command('recovery')['saved'])
        self.assertEqual(s.command('recovery')['reboots'],0)

    def test_open_handles_and_timers_reset_persistent_files_survive(self):
        folder=self.root/'storage/fls0';folder.mkdir(parents=True)
        saved=folder/'SAVE.dat';saved.write_bytes(b'preserve this saved game')
        s=self.session();p=0x08102000
        name='\\\\fls0\\SAVE.dat'.encode('utf-16-be')+b'\0\0'
        s.remote.write(p,name)
        handle=s.syscall(0x42c,p,0,0)
        self.assertEqual(s.syscall(0x42f,handle),24)
        s.remote.write(0xa8030000,bytes.fromhex('000b0009'))
        self.assertEqual(s.syscall(0x118,5,0xa8030000,1000),5)
        s.syscall(0xffff)
        self.assertEqual(s.command('status')['state'],'rebooted')
        self.assertEqual(saved.read_bytes(),b'preserve this saved game')
        # Old descriptor/timer state must not be usable after reset.
        self.assertGreaterEqual(s.syscall(0x42f,handle),0x80000000)
        self.assertEqual(s.syscall(0x11a,5),0xfffffffe)
        s.remote.write(p,name)
        new=s.syscall(0x42c,p,0,0)
        self.assertEqual(s.syscall(0x42f,new),24)

    def test_reload_failure_keeps_archived_and_live_fault(self):
        s=self.session();s.remote.write(0x88060000,b'KEEP')
        self.addin.unlink()
        s.syscall(0xffff)
        self.assertEqual(s.command('status')['reason'],'reload-failed')
        self.assertEqual(s.command('recovery')['reboots'],0)
        self.report(s,'unexpected-fault')
        self.assertEqual(s.remote.read_memory(0x88060000,4),b'KEEP')

    def test_exe_relaunch_gets_a_fresh_instruction_budget(self):
        s=Session(self.addin,self.root,['--step-limit','3'],fault_policy=None)
        self.addCleanup(s.close)
        s.syscall(0xffff)
        before=s.command('diagnostics')['executedSteps']
        s.command('key',key='EXE',down=True)
        s.remote.receive()
        s.command('key',key='EXE',down=False)
        self.assertEqual(s.command('status')['reason'],'step-limit')
        self.assertEqual(s.command('diagnostics')['executedSteps']-before,3)


if __name__=='__main__':unittest.main()
