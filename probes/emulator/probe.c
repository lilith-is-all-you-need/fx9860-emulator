#include "emu.h"
#include "g3a.h"
#include "platform.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <windows.h>

unsigned probe_frames(void);

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: preview-probe.exe ADDIN.g1a OUTPUT.png [key-script] [emulated-ms]\n");
        return 2;
    }
    G3aFile file;
    Emu *emu = calloc(1, sizeof *emu);
    if (!emu || !g3a_read(argv[1], &file)) return 3;
    if (!file.info.g1a) { fprintf(stderr, "probe requires .g1a\n"); g3a_close(&file); free(emu); return 3; }
    emu_set_clock(1767225600);
    const uint8_t id[8] = {0,1,2,3,4,5,6,7};
    emu_set_device_id(id);
    if (!emu_init(emu, MODEL_FX9750G3)) return 4;
    emu->headless = true;
    emu->trace = getenv("PROBE_TRACE") != NULL;
    emu->mem.trace_io = getenv("PROBE_TRACE_HW") != NULL;
    emu->cpu.trace_exceptions = emu->mem.trace_io;
    if (!g3a_map(emu, &file)) { emu_free(emu); g3a_close(&file); free(emu); return 5; }
    if (argc > 3 && !emu_parse_script(emu, argv[3])) return 6;
    emu_start(emu);
    uint64_t ms = argc > 4 ? strtoull(argv[4], NULL, 10) : 5000;
    if (ms > 60000) ms = 60000;
    uint64_t deadline = GetTickCount64() + 30000;
    uint64_t cycles = sh7305_iphi_hz(&emu->hw) / 1000;
    uint64_t limit = cycles * ms;
    bool down[256] = {false};
    bool timeout = false;
    while (emu->cpu.state == CPU_RUNNING && emu->cpu.instructions < limit) {
        if (GetTickCount64() >= deadline) { timeout = true; break; }
        emu_update_keys(emu, down);
        emu_run(emu, cycles * 10);
        emu_present(emu);
        if (argc > 3 && emu_script_finished(emu, 500)) break;
    }
    int w, h;
    const uint16_t *screen = emu_screen(emu, &w, &h);
    unsigned dark = 0;
    for (int i = 0; i < w*h; ++i) if (screen[i] != 0xFFFF) ++dark;
    bool saved = platform_save_image(argv[2], screen, w, h, 4);
    printf("PROBE_RESULT {\"model\":\"fx9750g3/fx9860g3\",\"cpu_state\":%d,\"cycles\":%" PRIu64 ",\"pc\":\"%08X\",\"frames\":%u,\"nonwhite_pixels\":%u,\"width\":%d,\"height\":%d,\"script_steps\":%d,\"script_consumed\":%d,\"timeout\":%s,\"saved\":%s}\n",
           emu->cpu.state, emu->cpu.instructions, emu->cpu.pc, probe_frames(), dark, w, h,
           emu->script_len, emu->script_pos, timeout ? "true" : "false", saved ? "true" : "false");
    if (emu->cpu.error[0]) fprintf(stderr, "CPU_ERROR: %s\n", emu->cpu.error);
    int status = timeout ? 9 : emu->cpu.state == CPU_ERROR ? 8 : !saved || emu->script_failed ? 7 : 0;
    emu_free(emu); free(emu); g3a_close(&file);
    return status;
}
