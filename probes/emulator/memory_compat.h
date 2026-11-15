/* Implementation of validated HLE bulk operations. Stage overlapping virtual
 * aliases and non-contiguous pages have memmove semantics too. */
static uint8_t *hle_byte(Emu *emu, uint32_t address, bool write)
{
    Memory *mem = &emu->mem;
    if(mem->probe_hw) return probe_hw_byte(mem, address, write);
    uint8_t *page = (write ? mem->wr : mem->rd)[address >> PAGE_SHIFT];
    if (page) return page + (address & (PAGE_SIZE - 1));
    /* P2 RAM/ROM is an uncached-region device in this model, not a flat page. */
    for (int i = 0; i < mem->uncached_count; ++i) {
        UncachedRegion *r = &mem->uncached[i];
        if (address >= r->base && address - r->base < r->size && (!write || r->writable))
            return r->host + (address - r->base);
    }
    return NULL;
}

static bool hle_span(Emu *emu, uint32_t address, uint32_t size, bool write)
{
    if (!size) return true;
    if ((uint64_t)address + size > UINT64_C(0x100000000)) goto invalid;
    for (uint64_t at = address, end = at + size; at < end;) {
        if (!hle_byte(emu, (uint32_t)at, write)) { address = (uint32_t)at; goto invalid; }
        at = (at & ~(uint64_t)1023) + 1024;
    }
    return true;
invalid:
    cpu_report(&emu->cpu, "HLE bulk %s invalid range at 0x%08X (size=%u)", write ? "write" : "read", address, size);
    emu->cpu.state = CPU_ERROR;
    return false;
}

static SC(sc_memcpy)
{
    uint32_t n = a[2];
    if (!n) return a[0];
    if (!hle_span(emu, a[0], n, true) || !hle_span(emu, a[1], n, false)) return 0;
    uint8_t *temporary = malloc(n);
    if (!temporary) { cpu_report(&emu->cpu, "HLE bulk copy host allocation failed"); emu->cpu.state = CPU_ERROR; return 0; }
    for (uint32_t i = 0; i < n; ++i) temporary[i] = *hle_byte(emu, a[1] + i, false);
    for (uint32_t i = 0; i < n; ++i) *hle_byte(emu, a[0] + i, true) = temporary[i];
    free(temporary);
    if (n <= INT32_MAX) { probe_debug_memory(a[1], (int)n, false); probe_debug_memory(a[0], (int)n, true); }
    return a[0];
}

static SC(sc_memset)
{
    uint32_t n = a[2];
    if (!n) return a[0];
    if (!hle_span(emu, a[0], n, true)) return 0;
    for (uint32_t i = 0; i < n; ++i) *hle_byte(emu, a[0] + i, true) = (uint8_t)a[1];
    if (n <= INT32_MAX) probe_debug_memory(a[0], (int)n, true);
    return a[0];
}
