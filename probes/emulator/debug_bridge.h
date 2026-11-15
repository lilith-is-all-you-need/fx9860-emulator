#ifndef FX_DEBUG_BRIDGE_H
#define FX_DEBUG_BRIDGE_H
#include "cpu.h"
#include <stdbool.h>
#include <stdint.h>
void probe_debug_before(Cpu *cpu, uint32_t address);
void probe_debug_poll(Cpu *cpu);
void probe_debug_memory(uint32_t address, int size, bool write);
extern bool probe_debug_ignore_memory;
int bridge_main(int argc, char **argv);
int bridge_wait_key(uint32_t timeout);
int probe_os_menu(Cpu *cpu);
void probe_clear_key_buffer(void);
void probe_request_reset(Cpu *cpu, const char *kind);
void bridge_frame(const uint16_t *pixels, int width, int height);
#endif
