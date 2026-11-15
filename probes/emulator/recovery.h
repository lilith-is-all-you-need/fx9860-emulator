/* Included by bridge.c: recovery only runs AFTER guest/OS callback stacks unwind.
 * This resets our HLE OS. No Casio boot firmware is present or claimed. */
void probe_request_reset(Cpu *cpu,const char *kind)
{
    snprintf(reset_kind,sizeof reset_kind,"%s",kind);
    cpu_report(cpu,"HLE reset requested (%s)",kind);
    cpu->state=CPU_ERROR;
}
static FILE *recovery_create(const wchar_t *path)
{
    HANDLE h=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(h==INVALID_HANDLE_VALUE)return NULL;
    int fd=_open_osfhandle((intptr_t)h,_O_BINARY|_O_WRONLY);
    if(fd<0){CloseHandle(h);return NULL;}
    FILE *f=_fdopen(fd,"wb");if(!f)_close(fd);return f;
}
static bool save_fault(void)
{
    wchar_t stem[32768],path[32768];
    if(wcslen(frame_path)>32600)return false;
    swprintf(stem,32768,L"%ls.fault-%lu-%llu-%u",frame_path,GetCurrentProcessId(),(unsigned long long)GetTickCount64(),++report_count);
    swprintf(path,32768,L"%ls.ram.bin",stem);
    FILE *f=recovery_create(path);if(!f)return false;
    bool ok=fwrite(machine->ram,1,active_layout.ram_size,f)==active_layout.ram_size;
    if(fclose(f))ok=false;
    if(!ok)return false;
    /* Snapshot the visible display before replacing the machine. */
    int w,h; const uint16_t *pixels=emu_screen(machine,&w,&h);
    bridge_frame(pixels,w,h);flush_frame(true);
    swprintf(path,32768,L"%ls.bmp",stem);
    if(!CopyFileW(frame_path,path,TRUE))return false;
    swprintf(path,32768,L"%ls.json",stem);
    char report_path[8192];
    if(!WideCharToMultiByte(CP_UTF8,0,path,-1,report_path,sizeof report_path,NULL,NULL))return false;
    f=recovery_create(path);if(!f)return false;
    Cpu *c=&machine->cpu; char error[2048],input[8192],trace[16384];
    json_escape(c->error,error,sizeof error);json_escape(addin_path,input,sizeof input);probe_trace_json(trace,sizeof trace);
    fprintf(f,"{\"schema\":1,\"model\":\"HLE\",\"kind\":\"%s\",\"addin\":\"%s\",\"error\":\"%s\",\"cycles\":%" PRIu64 ",\"registers\":{\"r\":[",reset_kind[0]?reset_kind:"unexpected-fault",input,error,c->instructions);
    for(int i=0;i<16;i++)fprintf(f,"%s%u",i?",":"",c->r[i]);
    fprintf(f,"],\"bank\":[");for(int i=0;i<8;i++)fprintf(f,"%s%u",i?",":"",c->bank[i]);
    fprintf(f,"],\"dsp\":[");for(int i=0;i<6;i++)fprintf(f,"%s%u",i?",":"",c->dsp[i]);
    fprintf(f,"],\"pc\":%u,\"opPc\":%u,\"pr\":%u,\"sr\":%u,\"gbr\":%u,\"vbr\":%u,\"mach\":%u,\"macl\":%u,\"ssr\":%u,\"spc\":%u,\"sgr\":%u,\"dbr\":%u,\"rs\":%u,\"re\":%u,\"mod\":%u,\"expevt\":%u,\"intevt\":%u,\"tea\":%u,\"tra\":%u,\"delaySlot\":%s},",
        c->pc,c->op_pc,c->pr,c->sr,c->gbr,c->vbr,c->mach,c->macl,c->ssr,c->spc,c->sgr,c->dbr,c->rs,c->re,c->mod,c->expevt,c->intevt,c->tea,c->tra,c->in_delay_slot?"true":"false");
    fprintf(f,"\"memoryFault\":{\"kind\":%u,\"address\":%u,\"write\":%s},\"ramBytes\":%u,\"recentPC\":[",machine->mem.fault,machine->mem.fault_addr,machine->mem.fault_write?"true":"false",active_layout.ram_size);
    uint64_t first=recent_pc_count>64?recent_pc_count-64:0;
    for(uint64_t i=first;i<recent_pc_count;i++)fprintf(f,"%s%u",i>first?",":"",recent_pc[i%64]);
    fprintf(f,"],\"hardware\":");probe_hw_snapshot(&machine->mem,f);
    fprintf(f,",\"syscalls\":%s}\n",trace);
    ok=!ferror(f);if(fclose(f))ok=false;if(ok)strcpy(last_report,report_path);return ok;
}
static void recovery_screen(void)
{
    /* A diagnostic recovery menu; it deliberately does not impersonate Casio UI. */
    const char *lines[]={"HLE OS restarted","Report saved","EXE: reload add-in"};
    for(int y=0;y<64;y++)for(int x=0;x<128;x++)latest_frame[y*128+x]=0xffff;
    /* Use the existing public bitmap font, avoiding writes into guest RAM. */
    for(int l=0;l<3;l++)for(unsigned k=0;lines[l][k];k++) {
        const uint8_t *glyph=platform_glyph(lines[l][k]);
        for(unsigned y=0;y<8;y++)for(unsigned x=0;x<5;x++)
            if(glyph[y] & (0x80u>>x))latest_frame[(8+l*16+y)*128+4+k*6+x]=0;
    }
    frame_width=128;frame_height=64;frame_dirty=true;flush_frame(true);
}
static bool recover_machine(void)
{
    fault_handled=true;
    if(!fault_saved)fault_saved=save_fault();
    if(!fault_saved){manual_reboot=false;fprintf(stderr,"Recovery snapshot failed; keeping live fault state\n");stopped(11,"report-failed");return false;}
    if(fault_pause && !manual_reboot){stopped(11,strstr(machine->cpu.error,"configured stack range")?"stack-range":"error");return true;}
    G3aFile addin={0};Emu *fresh=calloc(1,sizeof *fresh);
    bool ok=fresh && g3a_read(addin_path,&addin) && addin.info.g1a && emu_init(fresh,MODEL_FX9750G3) && g3a_map(fresh,&addin);
    g3a_close(&addin);
    if(ok){fresh->headless=false;fresh->layout=&active_layout;memcpy(fresh->rom+0x10020,active_layout.os_version,10);emu_start(fresh);ok=probe_hw_init(fresh,hardware_model);}
    if(ok&&os_firmware_path)ok=probe_hw_load_firmware(fresh,os_firmware_path,file_map_stress);
    if(!ok){if(fresh){emu_free(fresh);free(fresh);}manual_reboot=false;stopped(11,"reload-failed");return false;}
    /* Close file handles, release old RAM/MMU/cache/timers; persistent host files
       remain intact. Do not call a guest quit handler on a damaged machine. */
    emu_free(machine);free(machine);machine=fresh;
    memset(host_keys,0,sizeof host_keys);queued_key=-1;watch_pending=false;
    menu_waiting=false;menu_action=0;manual_reboot=false;
    memset(reset_kind,0,sizeof reset_kind);recent_pc_count=0;fault_handled=false;
    ++reboot_count;reboot_waiting=true;paused=true;step_budget=0;
    stopped(5,"rebooted");recovery_screen();
    fprintf(stderr,"HLE OS reset; fault report: %s\n",last_report);
    /* Keep the previous report visible, but archive the next fault separately. */
    fault_saved=false;
    return true;
}
