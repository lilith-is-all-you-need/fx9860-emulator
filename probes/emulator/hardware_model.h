#ifndef FX_HARDWARE_MODEL_H
#define FX_HARDWARE_MODEL_H
#include "cpu.h"
#include <stdio.h>
/* Functional SH7305 model. OS refill/lifecycle are explicit HLE policies. */
struct ProbeHardware;
struct EmuTag;
uint32_t probe_hw_read(Memory *, uint32_t, int);
void probe_hw_write(Memory *, uint32_t, uint32_t, int);
uint16_t probe_hw_fetch(Cpu *, uint32_t);
void probe_hw_ldtlb(Cpu *);
uint32_t probe_hw_tlb_refill(Cpu *);
void probe_hw_cache(Cpu *, uint16_t, uint32_t);
uint8_t *probe_hw_pointer(Memory *, uint32_t, uint32_t);
uint8_t *probe_hw_byte(Memory *, uint32_t, bool);
bool probe_hw_exit(Cpu *);
void probe_hw_register_quit(Cpu *, uint32_t);
void probe_hw_destroy(Memory *);
/* Emu is anonymous upstream; keep the public initializer opaque. */
bool probe_hw_init(void *emu, bool enable);
bool probe_hw_quit(void *emu);
bool probe_hw_enabled(const Memory *);
bool probe_hw_load_firmware(void *emu,const char *path,bool stress);
bool probe_hw_private_call(Cpu *);
bool probe_hw_file_stress(const Memory *);
void probe_hw_file_changed(void *emu);
uint32_t probe_hw_close_slot(Cpu *,uint32_t);
uint32_t probe_hw_close_search(Cpu *,uint32_t);
const char *probe_hw_os_version(const Memory *);
uint8_t *probe_hw_debug_byte(Memory *m, uint32_t a, bool write);
void probe_hw_snapshot(const Memory *, FILE *);
#endif
