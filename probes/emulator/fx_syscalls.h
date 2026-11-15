/* FX ABI additions. Sources/limits are recorded in SYSCALL-COVERAGE.md.
 * Inputs are guest addresses, never host pointers. Faults stay observable. */
static bool fx_ok(Emu *e) { return e->cpu.state == CPU_RUNNING && !e->mem.fault; }
static bool fx_partial_syscall(uint32_t n)
{
    /* Cursor storage works; glyph/blink/keyboard-driven updates are incomplete. */
    return n==0x1e7 || (n>=0x139 && n<=0x13b) || n==0x80e || n==0x80f || n==0x811 || n==0x812;
}
static SC(sc_fx_close_container_slot) { return probe_hw_close_slot(&emu->cpu,a[0]); }
static SC(sc_fx_close_search_slot) { return probe_hw_close_search(&emu->cpu,a[0]); }
static uint8_t fx_lower(uint8_t c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static uint8_t fx_upper(uint8_t c) { return c >= 'a' && c <= 'z' ? c - 32 : c; }
static SC(sc_fx_reset) { probe_request_reset(&emu->cpu, "syscall-0236"); return 0; }
static SC(sc_fx_system_os_version)
{
    /* FX 02EE is void System_GetOSVersion(unsigned char *version).
     * Ten ASCII characters (MM.mm.ssss) plus the terminating NUL. Use the
     * same modeled OS version as 0015; this does not identify real firmware.
     * Reference: Simon Lothar, fx_legacy_System.HTM. */
    const char *version = emu->layout->os_version ? emu->layout->os_version : "02.05.2201";
    if(!hle_span(emu,a[0],11,true))return 0;
    for(uint32_t i=0;i<10;i++)mem_write8(&emu->mem,a[0]+i,(uint8_t)version[i]);
    mem_write8(&emu->mem,a[0]+10,0);
    return 0; /* No documented return value. */
}
static SC(sc_fx_atoi)
{
    uint32_t p=a[0], value=0; uint8_t c; bool negative=false;
    do { c=mem_read8(&emu->mem,p++); } while(fx_ok(emu) && (c==' ' || (c>=9 && c<=13)));
    if(c=='-' || c=='+') { negative=c=='-'; c=mem_read8(&emu->mem,p++); }
    while(fx_ok(emu) && c>='0' && c<='9') { value=value*10+c-'0'; c=mem_read8(&emu->mem,p++); }
    return negative ? 0u-value : value;
}
static SC(sc_fx_hex)
{
    /* The historical return register is incidental; digits 0..8 are defined. */
    uint32_t n=a[2];
    if(n>8) { cpu_report(&emu->cpu,"LongToAscHex unsupported digit count %u",n); emu->cpu.state=CPU_ERROR; return 0; }
    if(!hle_span(emu,a[1],n+1,true))return 0;
    hex_write(emu,a[1],a[0],(int)n); mem_write8(&emu->mem,a[1]+n,0); return n;
}
static uint32_t fx_case(Emu *e,uint32_t p,bool upper)
{
    while(fx_ok(e)) { uint8_t c=mem_read8(&e->mem,p); if(!c)break;
        mem_write8(&e->mem,p++,upper?fx_upper(c):fx_lower(c)); }
    return 0;
}
static SC(sc_fx_upper) { return fx_case(emu,a[0],true); }
static SC(sc_fx_lower) { return fx_case(emu,a[0],false); }
static SC(sc_fx_casecmp)
{
    for(uint32_t i=0;fx_ok(emu);i++) {
        uint8_t x=fx_lower(mem_read8(&emu->mem,a[0]+i)), y=fx_lower(mem_read8(&emu->mem,a[1]+i));
        if(x!=y)return (uint32_t)((int)x-y);
        if(!x)break;
    } return 0;
}
static SC(sc_fx_invert)
{
    if((int32_t)a[1]<0 || !hle_span(emu,a[0],a[1],true))return 0;
    for(uint32_t i=0;i<a[1];i++)mem_write8(&emu->mem,a[0]+i,~mem_read8(&emu->mem,a[0]+i));
    return 0;
}
static SC(sc_fx_hex_byte) { uint32_t v; if(!hex_read(emu,a[0],2,&v))return UINT32_MAX; mem_write8(&emu->mem,a[1],v); return 1; }
static SC(sc_fx_hex_word) { uint32_t v; if(!hex_read(emu,a[0],4,&v))return UINT32_MAX; mem_write16(&emu->mem,a[1],v); return 1; }
static SC(sc_fx_hex_nibble) { mem_write8(&emu->mem,a[1],(uint8_t)hex_value(a[0])); return 0; }
static SC(sc_fx_strchr)
{
    for(uint32_t p=a[0];fx_ok(emu);p++) { uint8_t c=mem_read8(&emu->mem,p);
        if(c==(uint8_t)a[1])return p;
        if(!c)break;
    } return 0;
}
static SC(sc_fx_strstr)
{
    uint32_t needle[1]={a[1]}, n=sc_strlen(emu,needle);
    if(!n)return a[0];
    for(uint32_t p=a[0];fx_ok(emu);p++) { if(!mem_read8(&emu->mem,p))break;
        if(!str_compare(emu,p,a[1],n) && fx_ok(emu))return p; } return 0;
}
static SC(sc_fx_strcpy) { str_copy(emu,a[0],a[1],UINT32_MAX); return a[0]; }
static bool fx_mb_lead(uint8_t c) { return c==0x7f || (c>=0xe5 && c<=0xe7) || c==0xf7 || c==0xf9; }
static SC(sc_fx_mb_lead) { return fx_mb_lead(a[0]); }
static SC(sc_fx_mb_next) { return a[0]+(fx_mb_lead(mem_read8(&emu->mem,a[0]))?2:1); }
static SC(sc_fx_mb_get) { uint32_t c=mem_read8(&emu->mem,a[0]); return fx_mb_lead(c)?(c<<8)|mem_read8(&emu->mem,a[0]+1):c; }
static SC(sc_fx_mb_count)
{
    uint32_t count=0;
    for(uint32_t p=a[0];fx_ok(emu);count++) { uint8_t c=mem_read8(&emu->mem,p++); if(!c)break;
        if(fx_mb_lead(c)) { if(!mem_read8(&emu->mem,p++)) { cpu_report(&emu->cpu,"unterminated multibyte element"); emu->cpu.state=CPU_ERROR; break; } } }
    return count;
}
static SC(sc_fx_mb_ncat) { sc_strncat(emu,a); return a[1]; /* documented FX quirk */ }
static SC(sc_fx_mb_dup)
{
    uint32_t n=sc_strlen(emu,a); if(!fx_ok(emu) || n==UINT32_MAX)return 0;
    uint32_t p=heap_alloc(emu,n+1); if(p)str_copy(emu,p,a[0],n+1); return p;
}
static SC(sc_fx_name_length)
{
    uint32_t n=0; while(fx_ok(emu)) { uint16_t c=mem_read16(&emu->mem,a[0]+2*n); if(!c || c==0xffff)break; n++; } return n;
}
static SC(sc_fx_name_to_str)
{
    if((int32_t)a[2]<0 || !hle_span(emu,a[0],a[2],true))return 0;
    bool end=false; uint16_t c=0;
    for(uint32_t i=0;i<a[2] && fx_ok(emu);i++) { if(!end)c=mem_read16(&emu->mem,a[1]+2*i);
        if(!c || c==0xffff)end=true;
        mem_write8(&emu->mem,a[0]+i,(uint8_t)c);
    } return 0;
}
static SC(sc_fx_str_to_name)
{
    if(a[2]>INT32_MAX/2 || !hle_span(emu,a[0],2*a[2],true))return 0;
    bool end=false; uint16_t c=0;
    for(uint32_t i=0;i<a[2] && fx_ok(emu);i++) { if(!end)c=mem_read8(&emu->mem,a[1]+i);
        if(!c || c==0xff){end=true;if(c)c=0xffff;} mem_write16(&emu->mem,a[0]+2*i,c); } return 0;
}
static SC(sc_fx_device)
{
    uint32_t n=sc_fx_name_length(emu,a), p=a[0]; if(n<=3 || !fx_ok(emu))return UINT32_MAX;
    if(mem_read16(&emu->mem,p)=='\\' && mem_read16(&emu->mem,p+2)=='\\') {p+=4;n-=2;}
    if(n<4)return UINT32_MAX;
    char id[5]={0}; for(int i=0;i<4;i++)id[i]=(char)mem_read16(&emu->mem,p+2*i);
    return !strcmp(id,"fls0")?1:!strcmp(id,"crd0")?2:UINT32_MAX;
}
/* FX OS 042C adds 0x01000000 for fls0 and 0x02000000 for crd0.
 * Small integers are NOT storage handles: SDK libraries use their zero
 * device byte to select MCS. CG handlers keep their existing ABI. */
static int fx_file_index(Emu *e,uint32_t handle)
{
    unsigned tag=handle>>24,index=handle&0x00ffffffu;
    if((tag!=1&&tag!=2)||index>=sizeof e->files/sizeof e->files[0]||!e->files[index])return -1;
    return tag==e->fx_file_device[index]?(int)index:-1;
}
static SC(sc_fx_bfile_open)
{
    uint32_t tag=sc_fx_device(emu,a);
    if(tag!=1&&tag!=2)return (uint32_t)-1;
    uint32_t index=sc_bfile_open(emu,a);
    if((int32_t)index<0)return index;
    emu->fx_file_device[index]=(uint8_t)tag;
    return (tag<<24)|index;
}
#define FX_FILE_WRAPPER(name,original) \
static SC(name) { \
    int i=fx_file_index(emu,a[0]);if(i<0)return (uint32_t)-2; \
    uint32_t args[4]={(uint32_t)i,a[1],a[2],a[3]};return original(emu,args); \
}
FX_FILE_WRAPPER(sc_fx_bfile_close,sc_bfile_close)
FX_FILE_WRAPPER(sc_fx_bfile_size,sc_bfile_size)
FX_FILE_WRAPPER(sc_fx_bfile_seek,sc_bfile_seek)
FX_FILE_WRAPPER(sc_fx_bfile_read,sc_bfile_read)
FX_FILE_WRAPPER(sc_fx_bfile_write,sc_bfile_write)
#undef FX_FILE_WRAPPER
/* Cursor state follows the legacy API. Blink rendering remains unsupported. */
static SC(sc_fx_cursor_style)
{
    const int styles[]={0,1,2,4,8,0x10,0x11,0x12,0x14,0x18,0x40};
    for(unsigned i=0;i<sizeof styles/sizeof *styles;i++)if((int16_t)a[0]==styles[i]){emu->fx_cursor_style=styles[i];return 1;}
    return 0;
}
static SC(sc_fx_cursor_mode) { emu->fx_cursor_mode=a[0]!=0; return 0; }
static SC(sc_fx_cursor_state)
{
    uint32_t s[]={emu->cursor_x-1,emu->cursor_y-1,emu->fx_cursor_style,emu->fx_cursor_mode};
    for(int i=0;i<4;i++)mem_write32(&emu->mem,a[0]+4*i,s[i]);
    return emu->fx_cursor_mode;
}
static SC(sc_fx_cursor_on)
{
    const int style[]={0,1,-1,2,4,8,0x10,0x11,-1,0x12,0x14,0x18,0x40};
    unsigned v=(uint8_t)a[0]; if(v>=sizeof style/sizeof *style || style[v]<0)return 0;
    emu->fx_cursor_flash_style=v; emu->fx_cursor_style=style[v]; emu->fx_cursor_mode=1; return 0;
}
static SC(sc_fx_cursor_off) { emu->fx_cursor_mode=0; return 0; }
static SC(sc_fx_cursor_flash)
{
    const int style[]={0,1,-1,2,4,8,0x10,0x11,-1,0x12,0x14,0x18,0x40};
    for(unsigned n=0;n<sizeof style/sizeof *style;n++)if(style[n]==emu->fx_cursor_style)return n;
    return 0;
}
static SC(sc_fx_cursor_position_state)
{
    uint32_t s[]={emu->fx_cursor_mode?sc_fx_cursor_flash(emu,a):UINT32_MAX,emu->cursor_x,emu->cursor_y,0};
    for(int i=0;i<4;i++)mem_write32(&emu->mem,a[0]+4*i,s[i]);
    return 0;
}
