#include "co_utils.h"
#include "prf_types.h"
#include "user_custs1_def.h"
static const uint8_t service[16] = {1,0,0,0x50,0x58,0x14,0x10,0x9a,0x3d,0x4f,0x2b,0x7a,1,0,0xc0,0xcd};
static const uint8_t value[16] = {1,0,0,0x50,0x58,0x14,0x10,0x9a,0x3d,0x4f,0x2b,0x7a,2,0,0xc0,0xcd};
static const uint8_t task_value[16] = {1,0,0,0x50,0x58,0x14,0x10,0x9a,0x3d,0x4f,0x2b,0x7a,3,0,0xc0,0xcd};
static const uint16_t svc_decl = ATT_DECL_PRIMARY_SERVICE, char_decl = ATT_DECL_CHARACTERISTIC;
const uint8_t custs1_services[] = { CODEX_SVC, CUSTS1_IDX_NB };
const uint8_t custs1_services_size = 1;
const uint16_t custs1_att_max_nb = CUSTS1_IDX_NB;
const struct attm_desc_128 custs1_att_db[CUSTS1_IDX_NB] = {
    [CODEX_SVC] = {(uint8_t *)&svc_decl, ATT_UUID_128_LEN, PERM(RD, ENABLE), 16, 16, (uint8_t *)service},
    [CODEX_DECL] = {(uint8_t *)&char_decl, ATT_UUID_16_LEN, PERM(RD, ENABLE), 0, 0, NULL},
    [CODEX_VALUE] = {value, ATT_UUID_128_LEN, PERM(RD, ENABLE) | PERM(WR, ENABLE) | PERM(WRITE_REQ, ENABLE), PERM(RI, ENABLE) | 20, 0, NULL},
    [TASK_DECL] = {(uint8_t *)&char_decl, ATT_UUID_16_LEN, PERM(RD, ENABLE), 0, 0, NULL},
    [TASK_VALUE] = {task_value, ATT_UUID_128_LEN, PERM(RD, ENABLE) | PERM(WR, ENABLE) | PERM(WRITE_REQ, ENABLE) | PERM(WRITE_COMMAND, ENABLE), PERM(RI, ENABLE) | 244, 0, NULL}
};
