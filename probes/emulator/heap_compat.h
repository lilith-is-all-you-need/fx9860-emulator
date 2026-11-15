/* Implementation included by prepared syscalls.c. Guest heap metadata stays in guest
 * RAM. Validate complete block boundaries before mutation; never interpret an
 * interior pointer as a header. Zero-size allocations return NULL in this HLE.
 */
#define BLOCK_HEADER 8u
#define BLOCK_MIN 16u

static uint32_t heap_end(Emu *emu)
{
    return emu->layout->heap_base + emu->layout->heap_size;
}

static bool heap_error(Emu *emu, uint32_t address, const char *message)
{
    cpu_report(&emu->cpu, "HLE heap %s at 0x%08X", message, address);
    emu->cpu.state = CPU_ERROR;
    return false;
}

static bool heap_header(Emu *emu, uint32_t b, uint32_t *size, uint32_t *used)
{
    uint32_t end = heap_end(emu);
    if (b < emu->layout->heap_base || b > end - BLOCK_HEADER || (b & 7))
        return heap_error(emu, b, "invalid header address");
    *size = mem_read32(&emu->mem, b);
    *used = mem_read32(&emu->mem, b + 4);
    if (emu->mem.fault || *size < BLOCK_MIN || (*size & 7) || *size > end - b || *used > 1)
        return heap_error(emu, b, "corrupt header");
    return true;
}

static bool heap_init(Emu *emu)
{
    uint32_t base = emu->layout->heap_base, size = emu->layout->heap_size;
    if (emu->heap_ready) return true;
    if ((base | size) & 7 || size < BLOCK_MIN || size > UINT32_MAX - base ||
        !mem_ptr(&emu->mem, base, size))
        return heap_error(emu, base, "invalid layout");
    mem_write32(&emu->mem, base, size);
    mem_write32(&emu->mem, base + 4, 0);
    emu->heap_ready = true;
    return !emu->mem.fault;
}

static uint32_t heap_alloc(Emu *emu, uint32_t request)
{
    /* Compute in 64 bits before rounding, including allocator overhead. */
    uint64_t total = (((uint64_t)request + 7) & ~UINT64_C(7)) + BLOCK_HEADER;
    if (!request || total > emu->layout->heap_size || total > UINT32_MAX) return 0;
    if (!heap_init(emu)) return 0;
    uint32_t need = (uint32_t)total, end = heap_end(emu);
    for (uint32_t b = emu->layout->heap_base; b < end;) {
        uint32_t size, used;
        if (!heap_header(emu, b, &size, &used)) return 0;
        if (!used) {
            uint32_t combined = size;
            while (b + combined < end) {
                uint32_t next_size, next_used;
                if (!heap_header(emu, b + combined, &next_size, &next_used)) return 0;
                if (next_used) break;
                combined += next_size; /* each header was bounded by end */
            }
            if (combined >= need) {
                size = combined;
                if (size - need >= BLOCK_MIN) {
                    mem_write32(&emu->mem, b + need, size - need);
                    mem_write32(&emu->mem, b + need + 4, 0);
                    size = need;
                }
                mem_write32(&emu->mem, b, size);
                mem_write32(&emu->mem, b + 4, 1);
                return b + BLOCK_HEADER;
            }
            /* Coalesce validated free blocks, even when this request will fail. */
            mem_write32(&emu->mem, b, combined);
            size = combined;
        }
        b += size;
    }
    return 0;
}

static uint32_t heap_block(Emu *emu, uint32_t p)
{
    if (!p) return 0;
    if (!emu->heap_ready) { heap_error(emu, p, "pointer before first allocation"); return 0; }
    for (uint32_t b = emu->layout->heap_base; b < heap_end(emu);) {
        uint32_t size, used;
        if (!heap_header(emu, b, &size, &used)) return 0;
        if (b + BLOCK_HEADER == p) {
            if (used) return b;
            heap_error(emu, p, "double free or stale pointer");
            return 0;
        }
        b += size;
    }
    heap_error(emu, p, "invalid allocation pointer");
    return 0;
}

static SC(sc_malloc) { return heap_alloc(emu, a[0]); }

static SC(sc_calloc)
{
    uint64_t bytes = (uint64_t)a[0] * a[1];
    if (!bytes || bytes > UINT32_MAX) return 0;
    uint32_t p = heap_alloc(emu, (uint32_t)bytes);
    if (p) {
        uint8_t *host = mem_ptr(&emu->mem, p, (uint32_t)bytes);
        if (!host) { heap_error(emu, p, "unmapped allocation"); return 0; }
        memset(host, 0, (size_t)bytes);
        probe_debug_memory(p, (int)bytes, true);
    }
    return p;
}

static SC(sc_free)
{
    uint32_t b = heap_block(emu, a[0]);
    if (b) mem_write32(&emu->mem, b + 4, 0);
    return 0;
}

static SC(sc_realloc)
{
    if (!a[0]) return heap_alloc(emu, a[1]);
    uint32_t old = heap_block(emu, a[0]);
    if (!old) return 0;
    if (!a[1]) { mem_write32(&emu->mem, old + 4, 0); return 0; }
    uint32_t old_size = mem_read32(&emu->mem, old) - BLOCK_HEADER;
    if (a[1] <= old_size) return a[0];
    uint32_t p = heap_alloc(emu, a[1]);
    if (!p) return 0; /* failure retains the old allocation and contents */
    uint8_t *d = mem_ptr(&emu->mem, p, old_size), *s = mem_ptr(&emu->mem, a[0], old_size);
    if (!d || !s) { heap_error(emu, old, "unmapped realloc block"); return 0; }
    memmove(d, s, old_size);
    probe_debug_memory(a[0], (int)old_size, false);
    probe_debug_memory(p, (int)old_size, true);
    mem_write32(&emu->mem, old + 4, 0);
    return p;
}
