#ifndef CODEX_DISPLAY_H
#define CODEX_DISPLAY_H
#include <stdint.h>
#define NAME_BITMAP_BYTES (168*24/8)
#define TASK_BITMAP_BYTES (248*160/8)
struct __attribute__((packed)) quota_packet {
    uint8_t magic[2], version, remaining, resets, flags;
    uint32_t now, reset_at, window_minutes;
    uint16_t sequence;
};
extern volatile uint32_t display_frames;
void lcd_init(void);
void display_request(const struct quota_packet *, uint32_t now, unsigned connected, unsigned stale);
int display_step(void);
int display_busy(void);
void display_clock_request(uint32_t now);
void display_upgrade_request(unsigned stage, unsigned percent, unsigned phase);
void display_profile(unsigned theme, unsigned accent, const uint8_t *name);
void display_layout(unsigned layout);
void display_task_frame(const uint8_t *packed, unsigned length, unsigned kind, unsigned waiting, unsigned choices);
#endif
