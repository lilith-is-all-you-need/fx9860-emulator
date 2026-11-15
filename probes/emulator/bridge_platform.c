#include "platform.h"
#include "font.h"
#include "png.h"
#include "debug_bridge.h"
#include <stdio.h>
#include <string.h>

void platform_present(const uint16_t *fb, int w, int h) { bridge_frame(fb, w, h); }
void platform_clock(uint64_t ms) { (void)ms; }
int platform_wait_key(void) { return bridge_wait_key(UINT32_MAX); }
int platform_wait_key_timeout(uint32_t ms) { return bridge_wait_key(ms); }
void platform_flash(const char *msg) { fprintf(stderr, "platform: %s\n", msg); }
void platform_set_key_mode(bool shift, int alpha) { (void)shift; (void)alpha; }
void platform_set_os_status(const char *msg) { (void)msg; }
void platform_set_status_area_shown(bool shown) { (void)shown; }
void platform_set_language(int lang) { (void)lang; }
bool platform_save_image(const char *p, const uint16_t *px, int w, int h, int scale)
{ return png_save_rgb565(p, px, w, h, scale); }
bool platform_save_bmp(const char *p, const uint16_t *px, int w, int h)
{ (void)p; (void)px; (void)w; (void)h; return false; }
const uint8_t *platform_glyph(char c)
{
    static uint8_t rows[8]; memset(rows, 0, sizeof rows);
    const FontGlyph *g = font_glyph(&FONT_TINY, (unsigned char)c);
    if (g) for (unsigned y = 0; y < FONT_TINY.h && y < 8; ++y)
        rows[y] = FONT_TINY.bits[g->offset + y * ((g->w + 7) / 8)];
    return rows;
}
