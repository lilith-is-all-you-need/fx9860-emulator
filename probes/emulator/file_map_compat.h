/* Host-backed storage model. Fragmentation is opt-in stress behavior, not a
 * reproduction of the calculator's allocator or flash wear/compaction timing. */
static int copy_to_flash(Emu *emu,const char *path,FILE *f)
{
    struct stat st;if(fstat(fileno(f),&st)||st.st_size<0||(uint64_t)st.st_size>ADDIN_PHYS-FLASH_FILES)return -1;
    int i;for(i=0;i<emu->flash_file_count;i++)if(!strcmp(emu->flash_files[i].path,path))break;
    bool exists=i<emu->flash_file_count;
    if(exists&&emu->flash_files[i].size==(uint32_t)st.st_size&&emu->flash_files[i].mtime==(int64_t)st.st_mtime)return i;
    if(!exists&&i==(int)(sizeof emu->flash_files/sizeof emu->flash_files[0]))return -1;
    unsigned count=((uint32_t)st.st_size+4095)/4096;
    bool fragment=probe_hw_file_stress(&emu->mem)&&count>1&&count<=1024;
    bool reuse=exists&&emu->flash_files[i].page_count==count&&emu->flash_files[i].fragmented==fragment;
    uint32_t step=fragment?8192:4096,off=reuse?emu->flash_files[i].offset:(emu->flash_next+4095)&~4095u;
    uint64_t end=(uint64_t)off+(uint64_t)count*step;
    if(end+4096>ADDIN_PHYS)return -1;
    long pos=ftell(f);if(pos<0||fseek(f,0,SEEK_SET))return -1;
    unsigned remaining=(unsigned)st.st_size;
    for(unsigned page=0;page<count;page++) {
        uint32_t dest=off+page*step;unsigned n=remaining<4096?remaining:4096;
        memset(emu->rom+dest,0,4096);
        if(fread(emu->rom+dest,1,n,f)!=n){fseek(f,pos,SEEK_SET);return -1;}
        if(page<1024)emu->flash_files[i].pages[page]=dest;
        remaining-=n;
    }
    if(fseek(f,pos,SEEK_SET))return -1;
    if(!exists)emu->flash_file_count++;
    snprintf(emu->flash_files[i].path,sizeof emu->flash_files[i].path,"%s",path);
    emu->flash_files[i].offset=off;emu->flash_files[i].size=(uint32_t)st.st_size;
    emu->flash_files[i].mtime=(int64_t)st.st_mtime;emu->flash_files[i].page_count=count;
    emu->flash_files[i].fragmented=fragment;if(!reuse)emu->flash_next=(uint32_t)end;
    return i;
}
