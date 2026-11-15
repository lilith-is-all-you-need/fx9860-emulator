#include "hardware_model.h"
#include "emu.h"
#include <stdlib.h>
#include <string.h>
#include "../os-map-profile.h"
#include "syscall_trace.h"
#include "os/syscalls_impl.h"
SC(probe_bfile_offset_address);

typedef struct { uint32_t a, d, x; } Tlb;
typedef struct { uint32_t tag; uint64_t age; bool valid; uint8_t bytes[32]; } ILine;
typedef struct ProbeHardware {
    Emu *emu;
    Tlb u[64], i[4];
    uint32_t pteh, ptel, ptea, mmucr, ccr, quit;
    bool exiting;
    uint64_t age;
    ILine cache[128][4]; /* 16 KiB, 32-byte lines; replacement is functional LRU. */
    bool firmware, file_stress;
    FxOsMapProfile os;
    uint32_t search_slots;
    uint32_t original_pages[512];
    uint64_t file_rebuilds, table_refills;
    char version[11];
} Hardware;

void probe_hw_snapshot(const Memory *m,FILE *f)
{
    const Hardware *h=m->probe_hw;
    if(!h){fputs("null",f);return;}
    fprintf(f,"{\"pteh\":%u,\"ptel\":%u,\"ptea\":%u,\"mmucr\":%u,\"ccr\":%u,\"quitHandler\":%u,\"exiting\":%s,\"utlb\":[",h->pteh,h->ptel,h->ptea,h->mmucr,h->ccr,h->quit,h->exiting?"true":"false");
    for(int i=0;i<64;i++)fprintf(f,"%s[%u,%u,%u]",i?",":"",h->u[i].a,h->u[i].d,h->u[i].x);
    fputs("],\"itlb\":[",f);
    for(int i=0;i<4;i++)fprintf(f,"%s[%u,%u,%u]",i?",":"",h->i[i].a,h->i[i].d,h->i[i].x);
    fputs("],\"instructionCache\":[",f);bool first=true;
    for(int s=0;s<128;s++)for(int w=0;w<4;w++)if(h->cache[s][w].valid){
        const ILine *line=&h->cache[s][w];fprintf(f,"%s{\"set\":%d,\"way\":%d,\"tag\":%u,\"bytes\":\"",first?"":",",s,w,line->tag);first=false;
        for(int i=0;i<32;i++)fprintf(f,"%02x",line->bytes[i]);
        fputs("\"}",f);
    }
    fprintf(f,"],\"firmwareAssistedHle\":%s,\"fileMapStress\":%s,\"filePageTable\":%u,\"fileMapRebuilds\":%llu,\"tableRefills\":%llu}",h->firmware?"true":"false",h->file_stress?"true":"false",h->os.pages,(unsigned long long)h->file_rebuilds,(unsigned long long)h->table_refills);
}

static uint32_t raw_read(Memory *m, uint32_t a, int size)
{
    uint8_t *p = m->rd[a >> PAGE_SHIFT];
    return p && !(a & (size-1)) ? be_read(p+(a & (PAGE_SIZE-1)),size) : mem_read_slow(m,a,size);
}
static void raw_write(Memory *m, uint32_t a, uint32_t v, int size)
{
    uint8_t *p = m->wr[a >> PAGE_SHIFT];
    if(p && !(a & (size-1))) be_write(p+(a & (PAGE_SIZE-1)),v,size);
    else mem_write_slow(m,a,v,size);
}
static void error(Hardware *h, uint32_t a, bool write, const char *why)
{
    Memory *m=&h->emu->mem;
    if(!m->fault) { m->fault=FAULT_UNMAPPED; m->fault_addr=a; m->fault_write=write; }
    cpu_report(&h->emu->cpu,"SH7305 %s at %08X (no fabricated OS mapping)",why,a);
    h->emu->cpu.state=CPU_ERROR;
}
static unsigned page_size(uint32_t d)
{
    unsigned s=((d>>6)&2)|((d>>4)&1);
    return s==0?1024:s==1?4096:s==2?65536:1048576;
}
static bool match(Hardware *h, const Tlb *t, uint32_t a)
{
    bool shared=(t->d&2) || ((h->mmucr&0x100) && (h->emu->cpu.sr&SR_MD));
    return (t->a&0x100) && (t->d&0x100) &&
        (t->a & ~(page_size(t->d)-1)) == (a & ~(page_size(t->d)-1)) &&
        (shared || (t->a&255)==(h->pteh&255));
}
static int lookup(Hardware *h, Tlb *t, int count, uint32_t a)
{
    int found=-1;
    for(int k=0;k<count;k++) if(match(h,&t[k],a)) {
        if(found>=0) { error(h,a,false,"TLB multiple hit"); return -2; }
        found=k;
    }
    return found;
}
static unsigned advance_urc(Hardware *h)
{
    unsigned n=(h->mmucr>>10)&63, bound=(h->mmucr>>18)&63;
    if(!bound) bound=64;
    if(n>=bound) n=0;
    unsigned next=n+1; if(next>=bound) next=0;
    h->mmucr=(h->mmucr&~0xfc00u)|(next<<10);
    return n;
}
/* Only the OS-owned backing map can refill a miss. Temporary user mappings
 * have no hidden shadow page table and really disappear when evicted. */
static int os_refill(Hardware *h, uint32_t a)
{
    Emu *e=h->emu; Memory *m=&e->mem;
    if(h->firmware) {
        /* Proven OS path: 512 RAM entries, explicit software cursor 0..54.
         * The real internal handler lacks an upper bound. Diagnose that bad
         * access here instead of reproducing its out-of-table RAM read. */
        if(a<ADDIN_BASE || a>=ADDIN_BASE+0x200000u)return -1;
        uint32_t index=(a-ADDIN_BASE)>>12;
        uint32_t phys=raw_read(m,h->os.pages+index*4,4)&0x1fffffffu;
        if(!phys)return -1;
        unsigned slot=raw_read(m,h->os.cursor,4);
        if(slot>54){error(h,a,false,"invalid OS refill cursor");return -1;}
        h->pteh=a&~4095u;h->ptel=phys|0x17cu;
        h->mmucr=(h->mmucr&~0xfc00u)|(slot<<10);
        h->u[slot]=(Tlb){(a&~4095u)|0x300u,phys|0x17cu,0};
        raw_write(m,h->os.cursor,slot<54?slot+1:0,4);h->table_refills++;
        return (int)slot;
    }
    uint8_t *p=m->rd[a>>PAGE_SHIFT];
    if(!p) return -1;
    uintptr_t host=(uintptr_t)p, rom=(uintptr_t)e->rom, ram=(uintptr_t)e->ram;
    uint32_t phys, flags;
    if(host>=rom && host-rom<ROM_SIZE) { phys=(uint32_t)(host-rom); flags=0x15c; }
    else if(host>=ram && host-ram<e->layout->ram_size) {
        phys=e->layout->ram_phys+(uint32_t)(host-ram); flags=0x17c;
    } else return -1;
    unsigned n=advance_urc(h);
    h->u[n]=(Tlb){(a&~4095u)|0x300|(h->pteh&255),phys|flags,0};
    return (int)n;
}
static bool translate(Hardware *h,uint32_t a,bool fetch,bool write,uint32_t *pa,bool *cache)
{
    Cpu *cpu=&h->emu->cpu;
    *pa=a; *cache=(a>>29)==4;
    if(a>=0x80000000u && a<0xc0000000u) {
        if(!(cpu->sr&SR_MD)) { error(h,a,write,"privileged address"); return false; }
        return true;
    }
    if(a>=0xe0000000u) { *cache=false; return true; }
    if(!(h->mmucr&1)) { *pa=P1(a&0x1fffffff); *cache=true; return true; }
    if(h->mmucr&0x80) { error(h,a,write,"extended MMU mode unsupported"); return false; }
    int n=fetch?lookup(h,h->i,4,a):-1;
    if(n==-2) return false;
    Tlb *t=n>=0?&h->i[n]:NULL;
    if(!t) {
        int u=lookup(h,h->u,64,a);
        if(u==-2) return false;
        /* A guest-installed RAM vector owns translation misses. Let the CPU
         * enter VBR+0x400; the HLE OS must not silently refill its 512-page map. */
        if(u<0 && ((cpu->vbr>=0x88000000u&&cpu->vbr<0x88080000u)||
                   (cpu->vbr>=0xa8000000u&&cpu->vbr<0xa8080000u))) {
            Memory *m=&h->emu->mem;
            m->fault=FAULT_UNMAPPED;m->fault_addr=a;m->fault_write=write;
            return false;
        }
        if(u<0) u=os_refill(h,a);
        if(u<0) { error(h,a,write,"TLB miss"); return false; }
        t=&h->u[u];
        if(fetch) {
            /* Prefer invalid entries. A deterministic round-robin fallback;
             * do not advertise cycle/pseudo-LRU accurate replacement. */
            unsigned slot=4;
            for(unsigned k=0;k<4;k++) if(!(h->i[k].a&0x100)) { slot=k; break; }
            if(slot==4) slot=(unsigned)(h->age++&3);
            h->i[slot]=*t; t=&h->i[slot];
        } else advance_urc(h);
    }
    unsigned pr=(t->d>>5)&3;
    if((!(cpu->sr&SR_MD)&&pr<2) || (write&&!(pr&1))) {
        error(h,a,write,"TLB protection violation"); return false;
    }
    if(write&&!(t->d&4)) { error(h,a,true,"initial page write"); return false; }
    uint32_t mask=page_size(t->d)-1;
    *pa=P1((t->d&0x1ffffc00u&~mask)|(a&mask));
    *cache=(t->d&8)!=0;
    return true;
}
static uint32_t *reg(Hardware *h,uint32_t a)
{
    switch(a) {
    case 0xff000000:return &h->pteh; case 0xff000004:return &h->ptel;
    case 0xff000010:return &h->mmucr; case 0xff00001c:return &h->ccr;
    case 0xff000034:return &h->ptea;
    }
    unsigned k=(a>>8)&63;
    if((a&0xffffc0ffu)==0xf6000000u)return &h->u[k].a;
    if((a&0xffffc0ffu)==0xf7000000u)return &h->u[k].d;
    if((a&0xffffc0ffu)==0xf7800000u)return &h->u[k].x;
    k&=3;
    if((a&0xfffffcffu)==0xf2000000u)return &h->i[k].a;
    if((a&0xfffffcffu)==0xf3000000u)return &h->i[k].d;
    if((a&0xfffffcffu)==0xf3800000u)return &h->i[k].x;
    return NULL;
}
uint32_t probe_hw_read(Memory *m,uint32_t a,int size)
{
    Hardware *h=m->probe_hw; uint32_t *r=reg(h,a);
    if(r) {
        if(size!=4) { error(h,a,false,"non-long control access unsupported"); return 0; }
        return *r;
    }
    uint32_t pa; bool cached;
    if(!translate(h,a,false,false,&pa,&cached))return 0;
    return raw_read(m,pa,size);
}
void probe_hw_write(Memory *m,uint32_t a,uint32_t v,int size)
{
    Hardware *h=m->probe_hw; uint32_t *r=reg(h,a);
    if(r) {
        if(size!=4) { error(h,a,true,"non-long control access unsupported"); return; }
        *r=v;
        if(a==0xff000010 && (v&4)) {
            for(int n=0;n<64;n++) { h->u[n].a&=~0x100u; h->u[n].d&=~0x100u; }
            for(int n=0;n<4;n++) { h->i[n].a&=~0x100u; h->i[n].d&=~0x100u; }
            *r&=~4u;
        }
        if(a==0xff00001c) {
            if(v&0x800) memset(h->cache,0,sizeof h->cache);
            *r&=~0x808u; /* invalidate request bits self-clear */
        }
        /* V/D are shared fields between address/data array views. */
        unsigned k=(a>>8)&63;
        if((a&0xffffc0ffu)==0xf6000000u)
            h->u[k].d=(h->u[k].d&~0x104u)|(v&0x100)|((v>>7)&4);
        if((a&0xffffc0ffu)==0xf7000000u)
            h->u[k].a=(h->u[k].a&~0x300u)|(v&0x100)|((v&4)<<7);
        k&=3;
        if((a&0xfffffcffu)==0xf2000000u)h->i[k].d=(h->i[k].d&~0x100u)|(v&0x100);
        if((a&0xfffffcffu)==0xf3000000u)h->i[k].a=(h->i[k].a&~0x100u)|(v&0x100);
        return;
    }
    uint32_t pa; bool cached;
    if(translate(h,a,false,true,&pa,&cached)) raw_write(m,pa,v,size);
}
uint16_t probe_hw_fetch(Cpu *cpu,uint32_t a)
{
    Memory *m=cpu->mem; Hardware *h=m->probe_hw;
    if(!h)return mem_read16(m,a);
    if(a&1) { error(h,a,false,"unaligned instruction fetch");return 0; }
    uint32_t pa; bool cached;
    if(!translate(h,a,true,false,&pa,&cached))return 0;
    if(!cached || !(h->ccr&0x100))return (uint16_t)raw_read(m,pa,2);
    uint32_t tag=pa&~31u; ILine *set=h->cache[(a>>5)&127],*line=NULL;
    for(int i=0;i<4;i++)if(set[i].valid&&set[i].tag==tag)line=&set[i];
    if(!line) {
        line=&set[0];
        for(int i=0;i<4;i++)if(!set[i].valid||set[i].age<line->age)line=&set[i];
        for(int i=0;i<32;i++)line->bytes[i]=(uint8_t)raw_read(m,tag+(unsigned)i,1);
        if(m->fault)return 0;
        line->tag=tag;line->valid=true;
    }
    line->age=++h->age;
    return (uint16_t)be_read(line->bytes+(a&31),2);
}
void probe_hw_cache(Cpu *cpu,uint16_t op,uint32_t a)
{
    Hardware *h=cpu->mem->probe_hw;
    if(!h)return;
    if((op&0x00f0)==0x00e0) { /* ICBI; P2 is not instruction-cacheable. */
        uint32_t pa;bool cached;
        if(!translate(h,a,false,false,&pa,&cached)||!cached)return;
        ILine *set=h->cache[(a>>5)&127];
        for(int i=0;i<4;i++)if(set[i].tag==(pa&~31u))set[i].valid=false;
    }
    /* Operand accesses are an explicit coherent approximation. CCR=0x105
     * enables P1 copy-back; absence of delay in one probe is NOT proof of WT.
     * OCBP/OCBWB/SYNCO do not yet simulate operand cache lines or bus timing. */
}
void probe_hw_ldtlb(Cpu *cpu)
{
    Hardware *h=cpu->mem->probe_hw;if(!h)return;
    if(!(cpu->sr&SR_MD)) { error(h,cpu->pc,false,"privileged LDTLB");return; }
    unsigned slot=(h->mmucr>>10)&63;
    h->u[slot]=(Tlb){(h->pteh&0xfffffcffu)|(h->ptel&0x100)|((h->ptel&4)<<7),
                     h->ptel&0x1ffffdffu,h->ptea};
    /* Deliberately leave ITLB and I-cache stale, as observed on hardware. */
}
uint8_t *probe_hw_pointer(Memory *m,uint32_t a,uint32_t len)
{
    Hardware *h=m->probe_hw;uint32_t pa;bool cached;
    if(!len)len=1;
    if(a+len-1<a||!translate(h,a,false,false,&pa,&cached))return NULL;
    if(pa>=0xa0000000u&&pa<0xc0000000u)pa-=0x20000000u;
    uint8_t *p=m->rd[pa>>PAGE_SHIFT];if(!p)return NULL;
    p+=pa&(PAGE_SIZE-1);
    for(uint32_t n=0;n<len;) {
        uint32_t x;
        if(!translate(h,a+n,false,false,&x,&cached))return NULL;
        if(x>=0xa0000000u&&x<0xc0000000u)x-=0x20000000u;
        uint8_t *q=m->rd[x>>PAGE_SHIFT];
        if(!q||q+(x&(PAGE_SIZE-1))!=p+n)return NULL;
        uint32_t step=1024-((a+n)&1023); if(step>len-n)step=len-n;n+=step;
    }
    return p;
}
uint8_t *probe_hw_byte(Memory *m,uint32_t a,bool write)
{
    Hardware *h=m->probe_hw;uint32_t pa;bool cached;
    if(!translate(h,a,false,write,&pa,&cached))return NULL;
    if(pa>=0xa0000000u&&pa<0xc0000000u)pa-=0x20000000u;
    uint8_t *p=(write?m->wr:m->rd)[pa>>PAGE_SHIFT];
    return p?p+(pa&(PAGE_SIZE-1)):NULL;
}
bool probe_hw_enabled(const Memory *m){return m->probe_hw!=NULL;}
/* Debug reads must not refill/evict pages, populate caches or trigger MMIO. */
uint8_t *probe_hw_debug_byte(Memory *m,uint32_t a,bool write)
{
    Hardware *h=m->probe_hw; uint32_t pa=a;
    if(h && a<0x80000000u && (h->mmucr&1)) {
        Tlb *t=NULL;
        for(unsigned n=0;n<64;n++)if(match(h,&h->u[n],a)) {
            if(t)return NULL;
            t=&h->u[n];
        }
        if(t) {
            if(write&&!(t->d&0x20))return NULL;
            unsigned mask=page_size(t->d)-1;
            pa=P1((t->d&0x1ffffc00u&~mask)|(a&mask));
        }
    } else if(h && a<0x80000000u)pa=P1(a&0x1fffffff);
    if(pa>=0xa0000000u&&pa<0xc0000000u)pa-=0x20000000u;
    uint8_t *p=(write?m->wr:m->rd)[pa>>PAGE_SHIFT];
    return p?p+(pa&(PAGE_SIZE-1)):NULL;
}
bool probe_hw_init(void *ptr,bool enable)
{
    Emu *e=ptr;probe_hw_destroy(&e->mem);
    if(!enable)return true;
    Hardware *h=calloc(1,sizeof *h);if(!h)return false;
    e->mem.probe_hw=h;h->emu=e;h->ccr=0x105;h->mmucr=0x00fc0101;
    /* HLE starts with known OS pages. More OS pages refill on demand. */
    for(unsigned k=0;k<2;k++)os_refill(h,ADDIN_BASE+k*4096);
    for(unsigned k=0;k<e->layout->uram_size/4096 && k<32;k++)os_refill(h,URAM_BASE+k*4096);
    return true;
}
static uint8_t firmware_read(void *ctx,uint32_t a)
{Emu *e=ctx;return e->rom[a&0x1fffffffu];}
static void firmware_restore(Hardware *h)
{
    Memory *m=&h->emu->mem;
    for(unsigned i=0;i<512;i++)raw_write(m,h->os.pages+4*i,h->original_pages[i],4);
    raw_write(m,h->os.cursor,0,4);raw_write(m,h->os.enabled,1,1);
    memset(h->u,0,sizeof h->u);memset(h->i,0,sizeof h->i);
    for(unsigned i=0;i<8;i++) {
        uint32_t va=URAM_BASE+i*4096;uint8_t *p=m->rd[va>>PAGE_SHIFT];
        if(p && p>=h->emu->ram && p<h->emu->ram+h->emu->layout->ram_size) {
            uint32_t phys=h->emu->layout->ram_phys+(uint32_t)(p-h->emu->ram);
            h->u[55+i]=(Tlb){va|0x300,phys|0x17c,0};
        }
    }
    h->u[63]=(Tlb){0x300,0x17c,0};h->mmucr=0x00fcfd01;
}
bool probe_hw_load_firmware(void *ptr,const char *path,bool stress)
{
    Emu *e=ptr;Hardware *h=e->mem.probe_hw;if(!h)return false;
    FILE *f=fopen(path,"rb");if(!f)return false;
    bool ok=fseek(f,0,SEEK_END)==0&&ftell(f)==0x3b0000&&fseek(f,0,SEEK_SET)==0;
    if(ok)ok=fread(e->rom,1,0x3b0000,f)==0x3b0000;
    fclose(f);if(!ok||memcmp(e->rom+0x10000,"CASIOWIN",8))return false;
    int result=fx_os_profile(firmware_read,e,&h->os);
    if(result){fprintf(stderr,"unsupported OS mapping fingerprint: %d\n",result);return false;}
    /* 0218 is a distinct four-entry, 36-byte search descriptor pool.
     * Fingerprints agree in all nine supplied 3.40/3.60/3.71 branches. */
    uint32_t close_search=fx_word(firmware_read,e,h->os.table+0x218*4,4);
    if(!fx_rom(close_search,0x34)||fx_fingerprint(firmware_read,e,close_search,0x34)!=0xf4c8353bu)return false;
    uint32_t check=fx_literal(firmware_read,e,close_search+4);
    if(!fx_rom(check,40)||fx_fingerprint(firmware_read,e,check,40)!=0xd10b274eu)return false;
    h->search_slots=fx_literal(firmware_read,e,close_search+0x1c);
    if(h->search_slots<0x88000000u||h->search_slots>0x8803ff70u||
       h->search_slots!=fx_literal(firmware_read,e,check+12))return false;
    for(unsigned i=0;i<512;i++) {
        uint8_t *p=e->mem.rd[(ADDIN_BASE+i*4096)>>PAGE_SHIFT];
        uintptr_t v=(uintptr_t)p,base=(uintptr_t)e->rom;
        h->original_pages[i]=p&&v>=base&&v-base<ROM_SIZE?(uint32_t)(v-base):0;
    }
    h->firmware=true;h->file_stress=stress;
    memcpy(h->version,e->rom+0x10020,10);h->version[10]=0;
    /* Supplied 837A firmware branches derive 0200 from boot/features. Other
     * branches use their known model suffix; this is an explicit HLE model. */
    const char *suffix=(e->rom[0x302]=='5')?"2200":(e->rom[0x302]=='8')?"3200":"0200";
    memcpy(h->version+6,suffix,4);
    for(unsigned i=0;i<4;i++) {
        raw_write(&e->mem,h->search_slots+i*36,0x0ffe,2);
        raw_write(&e->mem,h->os.slots+i*8,0xffffffffu,4);
        raw_write(&e->mem,h->os.slots+i*8+4,0xff,1);
        for(unsigned n=0;n<40;n+=4)raw_write(&e->mem,h->os.descriptors+i*40+n,0,4);
    }
    firmware_restore(h);return true;
}
const char *probe_hw_os_version(const Memory *m)
{Hardware *h=m->probe_hw;return h&&h->firmware?h->version:NULL;}
bool probe_hw_file_stress(const Memory *m)
{Hardware *h=m->probe_hw;return h&&h->firmware&&h->file_stress;}
void probe_hw_file_changed(void *ptr)
{
    Emu *e=ptr;Hardware *h=e->mem.probe_hw;
    /* Deliberate stress trigger, not a claim every real OS write compacts.
     * The restore operation itself follows the observed OS map ownership. */
    if(h&&h->firmware&&h->file_stress&&raw_read(&e->mem,h->os.enabled,1)) {
        firmware_restore(h);h->file_rebuilds++;
    }
}
bool probe_hw_private_call(Cpu *cpu)
{
    Hardware *h=cpu->mem->probe_hw;if(!h||!h->firmware||cpu->pc!=h->os.query)return false;
    uint32_t args[12]={cpu->r[4],cpu->r[5],cpu->r[6],0};
    uint64_t id=probe_trace_enter(h->emu,0xffff0001u,args,"OS_FileOffsetToAddress_internal","firmware-derived-hle");
    cpu->r[0]=probe_bfile_offset_address(h->emu,args);
    if(cpu->state!=CPU_ERROR)cpu->pc=cpu->pr;
    probe_trace_leave(h->emu,id,cpu->r[0],cpu->state!=CPU_ERROR);cpu->attention=true;return true;
}
uint32_t probe_hw_close_slot(Cpu *cpu,uint32_t n)
{
    Hardware *h=cpu->mem->probe_hw;
    if(!h||n>=4){cpu_report(cpu,"01E7 index outside supported allocated slots");cpu->state=CPU_ERROR;return 0;}
    /* No internal-container open API exists in the baseline HLE, hence all
     * its slots are idle. Ordinary Bfile descriptors are a different pool. */
    if(!h->firmware)return UINT32_MAX;
    Memory *m=cpu->mem;uint32_t descriptor=h->os.descriptors+n*40;
    uint32_t flags=raw_read(m,descriptor+4,4);
    if((flags&0x80000000u)&&(flags&0x0fff0000u)==0x01200000u) {
        cpu_report(cpu,"01E7 dirty container commit remains unsupported");cpu->state=CPU_ERROR;return 0;
    }
    if(raw_read(m,h->os.slots+n*8+4,1)==0xff||raw_read(m,descriptor,2)>0xffe)return UINT32_MAX;
    raw_write(m,h->os.slots+n*8,UINT32_MAX,4);raw_write(m,h->os.slots+n*8+4,0xff,1);return 0;
}
uint32_t probe_hw_close_search(Cpu *cpu,uint32_t n)
{
    Hardware *h=cpu->mem->probe_hw;
    if(n>=4||!h||!h->firmware)return (uint32_t)-2;
    uint32_t slot=h->search_slots+n*36;
    if(raw_read(cpu->mem,slot,2)==0x0ffe)return (uint32_t)-2;
    raw_write(cpu->mem,slot,0x0ffe,2);return 0;
}
void probe_hw_destroy(Memory *m){free(m->probe_hw);m->probe_hw=NULL;}
void probe_hw_register_quit(Cpu *cpu,uint32_t fn)
{ Hardware *h=cpu->mem->probe_hw;if(h)h->quit=fn; }
bool probe_hw_quit(void *ptr)
{
    Emu *e=ptr;Hardware *h=e->mem.probe_hw;
    if(!h||!h->quit||h->exiting)return true;
    uint32_t fn=h->quit;h->quit=0;h->exiting=true;
    bool ok=cpu_call(&e->cpu,fn,100000000u);
    h->exiting=false;
    if(!ok&&e->cpu.state!=CPU_ERROR) {
        cpu_report(&e->cpu,"quit handler did not return within HLE budget");e->cpu.state=CPU_ERROR;
    }
    return ok;
}
bool probe_hw_exit(Cpu *cpu)
{
    Hardware *h=cpu->mem->probe_hw;
    return !h||probe_hw_quit(h->emu);
}
