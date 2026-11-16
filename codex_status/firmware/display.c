#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "display.h"
#include "fonts.inc"
#include "pairing.h"
#include "pairing_qr.inc"
#include "arch_wdg.h"
#define R16(a) (*(volatile uint16_t *)(a))
#define SPI R16(0x50001200)
#define TX R16(0x50001202)
#define SPI1 R16(0x50001208)
#define RGB(r,g,b) (((r)>>3)<<11 | ((g)>>2)<<5 | ((b)>>3))
#define BG colors[0]
#define INK colors[1]
#define MUTED colors[2]
#define TRACK colors[3]
#define GREEN accent_color
#define RED RGB(180,60,67)
#define AMBER RGB(148,97,0)
static uint16_t colors[4]={RGB(245,247,247),RGB(23,43,50),RGB(78,100,110),RGB(221,231,231)};
static uint16_t accent_color=RGB(18,113,90);
static uint8_t name_bitmap[NAME_BITMAP_BYTES];
static uint8_t task_bitmap[TASK_BITMAP_BYTES];
static uint8_t model_bitmap[MODEL_BITMAP_BYTES];
static uint8_t dim5[32], dim6[64];
static unsigned task_layout, task_kind, task_waiting, task_choices;

volatile uint32_t display_frames;
static uint16_t strip[240*4];
static unsigned column = 320, valid, connected, stale;
static unsigned top, bottom=240, upgrade_stage, upgrade_percent, upgrade_phase;
static uint32_t clock_now;
static struct quota_packet snapshot;
static const uint8_t init_data[] = {
#include "init.inc"
};
static void cs(unsigned high) { R16(high ? 0x50003042 : 0x50003044) = 2; }
static void dc(unsigned high) { R16(high ? 0x50003002 : 0x50003004) = 0x80; }
static void idle(void) { while (SPI1 & 8) {} }
static void mode(unsigned word, unsigned fifo) {
    idle(); SPI=0; SPI1=fifo|4; SPI=(word<<7)|0x11;
}
static void byte(uint8_t v) {
    R16(0x50001206)=1; TX=v;
    while (!(SPI&0x2000)) {}
    R16(0x50001206)=1; (void)TX;
}
static void command(uint8_t c, const uint8_t *p, unsigned n) {
    mode(0,3); cs(0); dc(0); byte(c); dc(1);
    while(n--) byte(*p++);
    cs(1);
}
static void delay(unsigned n) { while(n--) __asm volatile("nop"); }
void lcd_init(void) {
    display_brightness(100);
    R16(0x50000004)=(R16(0x50000004)&~0x300)|0x800;
    R16(0x50003002)=8;
    R16(0x5000300C)=0x300;
    R16(0x50003006)=0x300;
    R16(0x50003012)=0x300;
    R16(0x50003008)=0x307;
    R16(0x50003014)=0x300;
    R16(0x50003046)=0x306;
    R16(0x50003048)=0x300;
    R16(0x50003042)=0x0A;
    R16(0x5000304C)=0x300;
    R16(0x50003026)=0x300;
    R16(0x50003028)=0x200;
    R16(0x50000012)|=0x80;
    R16(0x50003022)=1; delay(100000);
    R16(0x50003024)=1; delay(100000);
    R16(0x50003022)=1; delay(600000);
    SPI=0; SPI1=3;
    for(unsigned i=0;i<sizeof(init_data);) {
        uint8_t c=init_data[i++], n=init_data[i++];
        command(c,init_data+i,n); i+=n;
        if(c==0x11) delay(600000);
    }
}
static void pixel(int x,int y,uint16_t color) {
    if(x>=(int)column && x<(int)column+4 && y>=0 && y<240)
        strip[(x-column)*240+239-y]=color;
}
static void rect(int x,int y,int w,int h,uint16_t color) {
    int end=x+w;
    if(x<(int)column) x=column;
    if(end>(int)column+4) end=column+4;
    for(int xx=x;xx<end;xx++) for(int yy=y;yy<y+h;yy++) pixel(xx,yy,color);
}
static unsigned decode(const char **str) {
    const unsigned char *s=(const unsigned char *)*str;
    unsigned c=*s++;
    if(c>=0xe0) { c=(c&15)<<12; c|=(*s++&63)<<6; c|=*s++&63; }
    else if(c>=0xc0) { c=(c&31)<<6; c|=*s++&63; }
    *str=(const char *)s; return c;
}
static int text(int x,int y,const char *str,unsigned size,uint16_t color) {
    const struct glyph *font=size==64?font64:size==20?font20:font14;
    const uint8_t *bits=size==64?font64_bits:size==20?font20_bits:font14_bits;
    unsigned count=size==64?sizeof(font64)/sizeof(*font):size==20?sizeof(font20)/sizeof(*font):sizeof(font14)/sizeof(*font);
    while(*str) {
        unsigned code=decode(&str), i;
        for(i=0;i<count && font[i].code!=code;i++) {}
        if(i==count) continue;
        const struct glyph *g=font+i;
        if(x+g->width>(int)column && x<(int)column+4) {
            unsigned stride=(g->width+7)/8;
            for(unsigned xx=0;xx<g->width;xx++) {
                if(x+(int)xx<(int)column || x+(int)xx>=(int)column+4) continue;
                for(unsigned yy=0;yy<g->height;yy++)
                    if(bits[g->offset+yy*stride+xx/8]&(0x80>>(xx&7))) pixel(x+xx,y+yy,color);
            }
        }
        x+=g->width;
    }
    return x;
}
static int leap(unsigned y) { return !(y%4) && (y%100 || !(y%400)); }
static void username(void) {
    for(unsigned x=0;x<168;x++) {
        if(x+20<column || x+20>=column+4) continue;
        for(unsigned y=0;y<24;y++)
            if(name_bitmap[y*21+x/8]&(0x80>>(x%8))) pixel(20+x,10+y,INK);
    }
}
static void date_string(char *out,uint32_t utc) {
    uint32_t t=utc+28800, days=t/86400;
    unsigned year=1970,month=1;
    const unsigned md[]={31,28,31,30,31,30,31,31,30,31,30,31};
    while(days>=365u+leap(year)) { days-=365u+leap(year); year++; }
    while(days>=md[month-1]+(month==2&&leap(year))) { days-=md[month-1]+(month==2&&leap(year)); month++; }
    snprintf(out,32,"%02u/%02lu %02lu:%02lu",month,(unsigned long)days+1,(unsigned long)(t/3600%24),(unsigned long)(t/60%60));
}
static void upgrade_scene(void) {
    static const int8_t points[24][2] = {
        {0,-46},{12,-44},{23,-40},{33,-33},{40,-23},{44,-12},
        {46,0},{44,12},{40,23},{33,33},{23,40},{12,44},
        {0,46},{-12,44},{-23,40},{-33,33},{-40,23},{-44,12},
        {-46,0},{-44,-12},{-40,-23},{-33,-33},{-23,-40},{-12,-44}
    };
    char buf[16];
    username();
    text(244,15,"无线升级",14,MUTED);
    for(unsigned i=0;i<24;i++) {
        uint16_t color=i*100<upgrade_percent*24?GREEN:TRACK;
        if(upgrade_stage<3 && (i+24-upgrade_phase%24)%24<3) color=RGB(85,203,153);
        if(upgrade_stage==3) color=GREEN;
        if(upgrade_stage==4) color=RED;
        for(int x=-3;x<=3;x++) for(int y=-3;y<=3;y++)
            if(x*x+y*y<=9) pixel(160+points[i][0]+x,100+points[i][1]+y,color);
    }
    if(upgrade_stage==3) {
        for(int i=0;i<13;i++) rect(141+i,100+i,4,4,GREEN);
        for(int i=0;i<27;i++) rect(153+i,112-i,4,4,GREEN);
    } else {
        snprintf(buf,sizeof(buf),"%u%%",upgrade_percent);
        text(upgrade_percent==100?133:140,91,buf,20,INK);
    }
    text(140,170,upgrade_stage==1?"传输":upgrade_stage==2?"校验":upgrade_stage==3?"完成":"失败",20,INK);
}
static void scene(void) {
    char buf[48];
    for(unsigned i=0;i<960;i++) strip[i]=BG;
    if(upgrade_stage) { upgrade_scene(); return; }
    if(!connected) {
        text(80,12,"扫码下载 Codex Desk",14,INK);
        int x0=(320-QR_SIZE*3)/2;
        rect(x0,39,QR_SIZE*3,QR_SIZE*3,0xffff);
        for(unsigned xx=column;xx<column+4;xx++) {
            if((int)xx<x0 || (int)xx>=x0+QR_SIZE*3) continue;
            unsigned x=(xx-x0)/3;
            for(unsigned y=0;y<QR_SIZE;y++)
                if(qr_bits[y*((QR_SIZE+7)/8)+x/8]&(0x80>>(x%8))) rect(xx,39+y*3,1,3,0);
        }
        text(139,174,"配对码",14,MUTED);
        text(74,195,pairing_code,20,INK);
        text(280,220,"离线",14,MUTED);
        return;
    }
    username();
    unsigned link_color=stale?RED:!valid?AMBER:GREEN;
    for(int x=-3;x<=3;x++) for(int y=-3;y<=3;y++)
        if(x*x+y*y<=9) pixel(198+x,22+y,link_color);
    if(clock_now) {
        uint32_t t=clock_now+28800;
        snprintf(buf,sizeof(buf),"%02lu:%02lu:%02lu",(unsigned long)(t/3600%24),(unsigned long)(t/60%60),(unsigned long)(t%60));
    } else strcpy(buf,"--:--:--");
    text(213,11,buf,20,INK);
    unsigned color=snapshot.remaining>70?RGB(35,169,115):snapshot.remaining>=50?RGB(211,164,22):snapshot.remaining>=20?RGB(232,124,45):RGB(222,76,85);
    text(279,53,stale?"离线":"剩余",14,stale?RED:MUTED);
    rect(288,99,8,93,TRACK);
    if(valid) {
        unsigned height=93*snapshot.remaining/100;
        rect(288,192-height,8,height,color);
    }
    if(valid) snprintf(buf,sizeof(buf),"%u%%",snapshot.remaining); else strcpy(buf,"--");
    text(277,75,buf,14,color);
    if(task_layout) {
        rect(16,82,248,1,TRACK);
        if(task_kind && task_choices && task_choices<=2) {
            for(unsigned i=0;i<task_choices;i++) rect(16+i*126,160,120,25,TRACK);
        }
        for(unsigned x=0;x<248;x++) {
            if(x+16<column || x+16>=column+4) continue;
            for(unsigned y=0;y<160;y++) {
                if(!(task_bitmap[y*31+x/8]&(0x80>>(x%8)))) continue;
                uint16_t ink=INK;
                if(y<20) ink=x>=168?RGB(70,135,210):x>=84?AMBER:MUTED;
                else if(y<49) ink=task_kind?AMBER:MUTED;
                else if(!task_kind && x>=164 && y>=53) {
                    unsigned row=(y-53)/33;
                    ink=(task_waiting&(1<<row))?AMBER:(task_waiting&(1<<(row+4)))?RGB(70,135,210):GREEN;
                }
                pixel(x+16,y+38,ink);
            }
        }
    } else {
        text(104,53,valid&&snapshot.window_minutes<10080?"本期剩余":"本周剩余",14,MUTED);
        if(valid) snprintf(buf,sizeof(buf),"%u",snapshot.remaining); else strcpy(buf,"--");
        unsigned width=strlen(buf)*(valid?38:28);
        int end=text((280-width-22)/2,87,buf,64,INK);
        text(end+4,127,"%",20,INK);
    }
    rect(16,199,288,1,TRACK);
    if(valid) date_string(buf,snapshot.reset_at); else strcpy(buf,"--/-- --:--");
    text(text(16,203,buf,14,MUTED)+3,203,"重置",14,MUTED);
    if(valid&&snapshot.resets!=255) snprintf(buf,sizeof(buf),"剩余 %u 次重置",snapshot.resets);
    else strcpy(buf,"剩余 -- 次重置");
    text(16,221,buf,14,INK);
    for(unsigned x=0;x<136;x++) {
        if(x+176<column || x+176>=column+4) continue;
        for(unsigned y=0;y<32;y++)
            if(model_bitmap[y*17+x/8]&(0x80>>(x%8))) pixel(176+x,203+y,MUTED);
    }
}
void display_layout(unsigned layout) { task_layout=layout; }
void display_brightness(unsigned percent) {
    for(unsigned i=0;i<32;i++) dim5[i]=i*percent/100;
    for(unsigned i=0;i<64;i++) dim6[i]=i*percent/100;
}
void display_model(unsigned offset,const uint8_t *data,unsigned length) { memcpy(model_bitmap+offset,data,length); }
void display_task_frame(const uint8_t *packed,unsigned length,unsigned kind,unsigned waiting,unsigned choices) {
    unsigned out=0;
    unsigned delta=kind&128;
    for(unsigned i=0;i<length;) {
        unsigned control=packed[i++], count=(control&127)+1;
        if(out+count>TASK_BITMAP_BYTES) return;
        if(control&128) { if(!delta) memset(task_bitmap+out,0,count); }
        else {
            if(i+count>length) return;
            if(delta) for(unsigned j=0;j<count;j++) task_bitmap[out+j]^=packed[i+j];
            else memcpy(task_bitmap+out,packed+i,count);
            i+=count;
        }
        out+=count;
    }
    task_kind=kind&127; task_waiting=waiting; task_choices=choices;
}
void display_profile(unsigned theme,unsigned accent,const uint8_t *name) {
    static const uint16_t palettes[2][4]={
        {RGB(245,247,247),RGB(23,43,50),RGB(78,100,110),RGB(221,231,231)},
        {RGB(17,26,30),RGB(233,242,239),RGB(145,165,164),RGB(46,62,65)}
    };
    static const uint16_t accents[2][3]={
        {RGB(18,113,90),RGB(39,101,178),RGB(185,101,29)},
        {RGB(111,216,173),RGB(121,181,246),RGB(244,176,105)}
    };
    memcpy(colors,palettes[theme],sizeof(colors));
    accent_color=accents[theme][accent];
    memcpy(name_bitmap,name,sizeof(name_bitmap));
}
void display_request(const struct quota_packet *p,uint32_t now,unsigned link,unsigned old) {
    valid=p!=0; if(p) memcpy(&snapshot,p,sizeof(snapshot));
    clock_now=now; connected=link; stale=old; column=0; top=0; bottom=240; upgrade_stage=0;
}
void display_clock_request(uint32_t now) { clock_now=now; column=208; top=8; bottom=33; }
void display_upgrade_request(unsigned stage,unsigned percent,unsigned phase) {
    upgrade_stage=stage; upgrade_percent=stage==3?100:percent; upgrade_phase=phase;
    column=0; top=0; bottom=240;
}
int display_busy(void) { return column<320; }
int display_step(void) {
    if(column>=320) return 0;
    scene();
    const uint32_t pins[]={0x50003006,0x5000300c,0x50003010,0x50003012,0x50003008,0x50003046};
    uint16_t saved[6], ctrl=SPI, ctrl1=SPI1;
    idle(); SPI=0;
    for(unsigned i=0;i<6;i++) saved[i]=R16(pins[i]);
    R16(0x50003002)=8;
    R16(pins[0])=0x300; R16(pins[1])=0x300; R16(pins[2])=0x200; R16(pins[3])=0x300;
    R16(pins[4])=0x307; R16(pins[5])=0x306;
    uint8_t p[4]={0,240-bottom,0,239-top}; command(0x2a,p,4);
    p[0]=column>>8; p[1]=column; p[2]=(column+3)>>8; p[3]=column+3;
    command(0x2b,p,4); command(0x2c,p,0);
    mode(1,2); dc(1); cs(0);
    for(unsigned x=0;x<4;x++) for(unsigned y=240-bottom;y<240-top;y++) {
        uint16_t color=strip[x*240+y];
        while(SPI&0x800) {} TX=(dim5[color>>11]<<11)|(dim6[(color>>5)&63]<<5)|dim5[color&31];
    }
    idle(); cs(1); R16(0x50001206)=1; (void)TX; SPI=0;
    for(unsigned i=0;i<6;i++) R16(pins[i])=saved[i];
    SPI1=ctrl1; SPI=ctrl;
    column+=4;
    wdg_reload(WATCHDOG_DEFAULT_PERIOD);
    if(column==320) display_frames++;
    return column<320;
}
