#include "syscall_trace.h"
#include <inttypes.h>
#include <stdarg.h>
#include <string.h>

#define TRACE_COUNT 16
typedef struct {
    uint64_t id, steps;
    uint32_t number, caller, sp, args[4], result;
    const char *name, *kind;
    bool completed, returned, failed;
} Event;
static Event recent[TRACE_COUNT];
static uint64_t total, implemented, partial, stubs, missing;
static FILE *trace_file;
static bool strict;

void probe_trace_configure(FILE *output, bool strict_stubs)
{
    memset(recent, 0, sizeof recent);
    total = implemented = partial = stubs = missing = 0;
    trace_file = output;
    strict = strict_stubs;
}
bool probe_trace_strict(void) { return strict; }

static void format_event(const Event *e, char *out, size_t capacity)
{
    /* Names/kinds originate in the compiled syscall table, not guest strings. */
    snprintf(out, capacity,
        "{\"id\":%" PRIu64 ",\"number\":%u,\"name\":\"%s\",\"kind\":\"%s\","
        "\"caller\":\"%08X\",\"sp\":\"%08X\",\"args\":[%u,%u,%u,%u],"
        "\"cycles\":%" PRIu64 ",\"completed\":%s,\"returned\":%s,\"result\":%u,\"failed\":%s}",
        e->id, e->number, e->name, e->kind, e->caller, e->sp,
        e->args[0], e->args[1], e->args[2], e->args[3], e->steps,
        e->completed ? "true" : "false", e->returned ? "true" : "false", e->result,
        e->failed ? "true" : "false");
}
static void emit(const Event *e, const char *phase)
{
    if (!trace_file) return;
    char record[768];
    format_event(e, record, sizeof record);
    fprintf(trace_file, "{\"phase\":\"%s\",\"call\":%s}\n", phase, record);
    fflush(trace_file);
}
uint64_t probe_trace_enter(Emu *emu, uint32_t number, const uint32_t *args,
                          const char *name, const char *kind)
{
    uint64_t id = ++total;
    Event *e = &recent[(id - 1) % TRACE_COUNT];
    *e = (Event){.id = id, .number = number, .caller = emu->cpu.pr,
                 .sp = emu->cpu.r[15], .steps = emu->cpu.instructions,
                 .name = name, .kind = kind};
    memcpy(e->args, args, sizeof e->args);
    if (!strcmp(kind, "stub")) ++stubs;
    else if (!strcmp(kind, "missing")) ++missing;
    else if (!strcmp(kind, "partial")) ++partial;
    else ++implemented;
    emit(e, "enter");
    return id;
}
void probe_trace_leave(Emu *emu, uint64_t id, uint32_t result, bool returned)
{
    Event *e = &recent[(id - 1) % TRACE_COUNT];
    /* A deeply nested callback may evict the parent. Do not corrupt another event. */
    if (e->id != id) return;
    e->completed = true;
    e->returned = returned;
    e->result = result;
    e->failed = emu->cpu.state == CPU_ERROR || emu->mem.fault;
    emit(e, "leave");
}
void probe_trace_json(char *buffer, size_t capacity)
{
    if (capacity < 16384) { if (capacity) snprintf(buffer, capacity, "{\"ok\":false}"); return; }
    int n = snprintf(buffer, capacity,
        "{\"ok\":true,\"total\":%" PRIu64 ",\"implemented\":%" PRIu64
        ",\"partial\":%" PRIu64 ",\"stubs\":%" PRIu64 ",\"missing\":%" PRIu64 ",\"strictStubs\":%s,\"recent\":[",
        total, implemented, partial, stubs, missing, strict ? "true" : "false");
    uint64_t start = total > TRACE_COUNT ? total - TRACE_COUNT : 0;
    for (uint64_t i = start; i < total; ++i) {
        if (i != start) buffer[n++] = ',';
        char record[768];
        format_event(&recent[i % TRACE_COUNT], record, sizeof record);
        size_t length = strlen(record);
        memcpy(buffer + n, record, length);
        n += (int)length;
    }
    memcpy(buffer + n, "]}\n", 4);
}
