#ifndef FX_SYSCALL_TRACE_H
#define FX_SYSCALL_TRACE_H
#include "emu.h"
#include <stddef.h>
#include <stdio.h>
void probe_trace_configure(FILE *output, bool strict_stubs);
uint64_t probe_trace_enter(Emu *emu, uint32_t number, const uint32_t *args,
                          const char *name, const char *kind);
void probe_trace_leave(Emu *emu, uint64_t id, uint32_t result, bool returned);
bool probe_trace_strict(void);
void probe_trace_json(char *buffer, size_t capacity);
#endif
