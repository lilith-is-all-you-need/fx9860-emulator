#include "platform.h"
#include "font.h"
#include "png.h"
#include <stdio.h>
#include <string.h>

static unsigned frames;
unsigned probe_frames(void) { return frames; }
void platform_present(const uint16_t *fb, int w, int h) { (void)fb; (void)w; (void)h; ++frames; }
void platform_clock(uint64_t ms) { (void)ms; }
int platform_wait_key(void) { return -1; }
int platform_wait_key_timeout(uint32_t ms) { (void)ms; return -1; }
void platform_flash(const char *msg) { fprintf(stderr, "platform: %s\n", msg); }
void platform_set_key_mode(bool shift, int alpha) { (void)shift; (void)alpha; }
void platform_set_os_status(const char *msg) { (void)msg; }
void platform_set_status_area_shown(bool shown) { (void)shown; }
void platform_set_language(int lang) { (void)lang; }
bool platform_save_image(const char *p, const uint16_t *px, int w, int h, int scale)
{
    return png_save_rgb565(p, px, w, h, scale);
}
/* This probe emits PNG bytes only. Do not pretend that a .bmp filename is BMP. */
bool platform_save_bmp(const char *p, const uint16_t *px, int w, int h)
{
    (void)p; (void)px; (void)w; (void)h;
    fprintf(stderr, "probe: BMP output is not implemented; use .png screenshots\n");
    return false;
}
const uint8_t *platform_glyph(char c)
{
    static uint8_t rows[8];
    memset(rows, 0, sizeof rows);
    const FontGlyph *g = font_glyph(&FONT_TINY, (unsigned char)c);
    if (g) {
        unsigned stride = (g->w + 7) / 8;
        for (unsigned y = 0; y < FONT_TINY.h && y < 8; ++y)
            rows[y] = FONT_TINY.bits[g->offset + y * stride];
    }
    return rows;
}
