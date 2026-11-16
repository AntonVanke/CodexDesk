#include <string.h>
#include "user_peripheral.h"
#include "app_easy_timer.h"
#include "custs1_task.h"
#include "user_custs1_def.h"
#include "display.h"
#include "app_suotar.h"
#include "spi.h"
#include "spi_flash.h"
#include "arch.h"
#include "pairing.h"

volatile struct quota_packet received;
volatile uint32_t packets_received;
static uint32_t current_time, age;
static uint8_t connected, has_data, dirty, waiting_ack;
static uint8_t connection_index;
static timer_hnd pairing_timer;
static uint8_t clock_dirty, upgrade_stage, upgrade_dirty;
static unsigned animation_phase;
static uint8_t pending_theme, pending_accent, pending_name[NAME_BITMAP_BYTES];
static uint8_t task_packed[5000], task_kind, task_waiting, task_choices;
static uint16_t task_length, task_received;
static uint8_t task_pending, task_rendering;
static struct __attribute__((packed)) { uint16_t sequence; uint8_t ready, reserved; } task_ack;

void user_suota_status(uint8_t event) {
    if (event == SUOTAR_START) {
        GPIO_set_pad_latch_en(true);
        const spi_cfg_t spi_cfg = {
            .spi_ms=SPI_MS_MODE_MASTER, .spi_cp=SPI_CP_MODE_0,
            .spi_speed=SPI_SPEED_MODE_4MHz, .spi_wsz=SPI_MODE_8BIT,
            .spi_cs=SPI_CS_0, .spi_irq=SPI_IRQ_DISABLED,
            .cs_pad={GPIO_PORT_0, GPIO_PIN_3},
        };
        const spi_flash_cfg_t flash_cfg = {0xfe, 0xa14013, 0x80000};
        SetWord16(SPI_CTRL_REG,0);
        SetWord16(SPI_CTRL_REG1,0);
        spi_initialize(&spi_cfg);
        spi_flash_configure_env(&flash_cfg);
        upgrade_stage=1;
    } else upgrade_stage=2;
    upgrade_dirty=1;
}

static void animation_tick(void) {
    animation_phase++;
    if (upgrade_stage) upgrade_dirty=1;
    app_easy_timer(20, animation_tick);
}

static void tick(void) {
    if (has_data) { current_time++; age++; }
    if (has_data) clock_dirty=1;
    if (has_data && (age % 60 == 0 || age == 180)) dirty = 1;
    app_easy_timer(100, tick);
}
void user_app_init(void) {
    default_app_on_init();
    lcd_init();
    pairing_init();
    dirty = 1;
}
void user_app_db_init_complete(void) {
    app_easy_timer(100, tick);
    app_easy_timer(20, animation_tick);
    default_app_on_db_init_complete();
}
void user_app_adv_start(void) { pairing_advertise(); app_easy_gap_undirected_advertise_start(); }
void user_app_adv_undirect_complete(uint8_t status) {
    if (status == GAP_ERR_CANCELED) user_app_adv_start();
}
static void pairing_expired(void) {
    pairing_timer=EASY_TIMER_INVALID_TIMER;
    if(!connected) app_easy_gap_disconnect(connection_index);
}
void user_app_connection(uint8_t idx, struct gapc_connection_req_ind const *param) {
    connected = 0; dirty = 1; connection_index=idx;
    default_app_on_connection(idx, param);
    pairing_timer=app_easy_timer(3000,pairing_expired);
}
void user_app_encrypted(uint8_t idx,uint8_t auth) {
    (void)idx;
    connected=(auth&GAP_AUTH_MITM)!=0; dirty=1;
    if(pairing_timer) { app_easy_timer_cancel(pairing_timer); pairing_timer=EASY_TIMER_INVALID_TIMER; }
}
void user_app_paired(uint8_t idx) {
    default_app_on_pairing_succeeded(idx);
    user_app_encrypted(idx,GAP_AUTH_MITM);
}
void user_app_disconnect(struct gapc_disconnect_ind const *param) {
    (void)param;
    if (suota_state.reboot_requested) platform_reset(RESET_AFTER_SUOTA_UPDATE);
    if (upgrade_stage) { app_suotar_reset(); upgrade_stage=0; }
    connected = 0; dirty = 1;
    if(pairing_timer) { app_easy_timer_cancel(pairing_timer); pairing_timer=EASY_TIMER_INVALID_TIMER; }
    pairing_new_code();
    task_pending=0; task_rendering=0;
    user_app_adv_start();
}
arch_main_loop_callback_ret_t user_app_system_powered(void) {
    if (display_busy()) return display_step() ? KEEP_POWERED : GOTO_SLEEP;
    if (upgrade_stage) {
        if (upgrade_dirty) {
            unsigned percent=suota_state.suota_image_len ? 100*suota_state.suota_img_idx/suota_state.suota_image_len : 0;
            display_upgrade_request(upgrade_stage, percent, animation_phase);
            upgrade_dirty=0;
        }
        return display_step() ? KEEP_POWERED : GOTO_SLEEP;
    }
    if (waiting_ack && !dirty) { received.flags |= 0x80; waiting_ack = 0; }
    if (task_rendering) { task_ack.ready=1; task_rendering=0; }
    if (task_pending) {
        display_task_frame(task_packed,task_length,task_kind,task_waiting,task_choices);
        task_pending=0; task_rendering=1; dirty=1;
    }
    if (dirty) {
        display_request(has_data ? (const struct quota_packet *)&received : 0,
                        current_time, connected, age >= 180);
        dirty = 0; clock_dirty=0;
    } else if (clock_dirty) {
        display_clock_request(current_time); clock_dirty=0;
    }
    if (display_step()) return KEEP_POWERED;
    return GOTO_SLEEP;
}
void user_catch_rest_hndl(ke_msg_id_t msgid, void const *param, ke_task_id_t dest, ke_task_id_t src) {
    (void)dest;
    if (msgid == CUSTS1_VAL_WRITE_IND) {
        const struct custs1_val_write_ind *m = param;
        if(!connected) return;
        if(m->handle==CODEX_VALUE && m->length==2 && m->value[0]=='C' && m->value[1]=='F') {
            pairing_forget(); app_easy_gap_disconnect(connection_index); return;
        }
        if (m->handle==TASK_VALUE) {
            if(m->length==8 && m->value[0]=='B') {
                task_ack.sequence=m->value[1]|(m->value[2]<<8); task_ack.ready=0;
                task_length=m->value[3]|(m->value[4]<<8); task_received=0;
                task_kind=m->value[5]; task_waiting=m->value[6]; task_choices=m->value[7];
            } else if(m->length>3 && m->value[0]=='D') {
                unsigned offset=m->value[1]|(m->value[2]<<8), count=m->length-3;
                if(offset==task_received && offset+count<=sizeof(task_packed)) {
                    memcpy(task_packed+offset,m->value+3,count); task_received+=count;
                }
            } else if(m->length==1 && m->value[0]=='E') {
                if(task_received==task_length && task_length) task_pending=1;
                else task_ack.ready=2;
            }
            return;
        }
        if (m->handle==CODEX_VALUE && m->length==3 && m->value[0]=='C' && m->value[1]=='L') {
            display_layout(m->value[2]); dirty=1; return;
        }
        if (m->handle==CODEX_VALUE && m->length==4 && m->value[0]=='C' && m->value[1]=='S') {
            pending_theme=m->value[2]; pending_accent=m->value[3]; return;
        }
        if (m->handle==CODEX_VALUE && m->length>4 && m->value[0]=='C' && m->value[1]=='N') {
            unsigned offset=m->value[2]|(m->value[3]<<8);
            memcpy(pending_name+offset,m->value+4,m->length-4); return;
        }
        if (m->handle==CODEX_VALUE && m->length==2 && m->value[0]=='C' && m->value[1]=='A') {
            display_profile(pending_theme,pending_accent,pending_name); dirty=1; return;
        }
        if (m->handle==CODEX_VALUE && m->length==3 && m->value[0]=='C' && m->value[1]=='U') {
            upgrade_stage=m->value[2]; upgrade_dirty=1; dirty=1; return;
        }
        if (m->handle != CODEX_VALUE || m->length != sizeof(struct quota_packet)) return;
        const struct quota_packet *p = (const struct quota_packet *)m->value;
        if (p->magic[0] != 'C' || p->magic[1] != 'D' || p->version != 1 || p->remaining > 100 || !(p->flags & 1)) return;
        memcpy((void *)&received, p, sizeof(received));
        received.flags &= 0x7f;
        current_time = p->now; age = 0; has_data = 1;
        packets_received++; dirty = 1; waiting_ack = 1;
    } else if (msgid == CUSTS1_VALUE_REQ_IND) {
        const struct custs1_value_req_ind *m = param;
        unsigned length=m->att_idx==TASK_VALUE?sizeof(task_ack):sizeof(received);
        const void *value=m->att_idx==TASK_VALUE?(const void *)&task_ack:(const void *)&received;
        struct custs1_value_req_rsp *rsp = KE_MSG_ALLOC_DYN(CUSTS1_VALUE_REQ_RSP, src, TASK_APP,
                                                           custs1_value_req_rsp, length);
        rsp->conidx = m->conidx; rsp->att_idx = m->att_idx;
        rsp->status = ATT_ERR_NO_ERROR; rsp->length = length;
        memcpy(rsp->value, value, length);
        ke_msg_send(rsp);
    }
}
