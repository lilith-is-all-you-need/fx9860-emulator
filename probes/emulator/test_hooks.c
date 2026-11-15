#include "debug_bridge.h"
#include "syscall_trace.h"
#include <stdlib.h>
bool probe_debug_ignore_memory;
void probe_debug_before(Cpu *cpu, uint32_t address) { (void)cpu; (void)address; }
void probe_debug_poll(Cpu *cpu) { (void)cpu; }
void probe_debug_memory(uint32_t address, int size, bool write) { (void)address; (void)size; (void)write; }
/* The upstream CPU-only harness has no Emu/OS/file layer. Reaching any of
 * these dependencies is a test error, never an emulated successful syscall. */
uint64_t probe_trace_enter(Emu *emu,uint32_t number,const uint32_t *args,const char *name,const char *kind)
{ (void)emu;(void)number;(void)args;(void)name;(void)kind;abort(); }
void probe_trace_leave(Emu *emu,uint64_t id,uint32_t result,bool returned)
{ (void)emu;(void)id;(void)result;(void)returned;abort(); }
uint32_t probe_bfile_offset_address(Emu *emu,const uint32_t *args)
{ (void)emu;(void)args;abort(); }
