/* Internal FX function ABI recovered from the supplied OS images. */
SC(probe_bfile_offset_address)
{
    uint32_t handle=a[0]&0x00ffffffu;
    if((a[0]>>24)!=1)return (uint32_t)-2;
    FILE *f=handle_file(emu,handle);if(!f||(int32_t)a[1]<0)return (uint32_t)-2;
    if(emu->fx_file_device[handle]!=1)return (uint32_t)-2;
    int i=emu->file_flash[handle];if(i<0||i>=emu->flash_file_count)return (uint32_t)-5;
    if(a[1]>=emu->flash_files[i].size)return 0;
    /* Dirty host copies must be refreshed through a new Bfile open; never
     * quietly return a stale physical address as if it were current data. */
    if(emu->flash_files[i].mtime==INT64_MIN)return (uint32_t)-5;
    uint32_t page=a[1]>>12,off=a[1]&4095;
    uint32_t phys=emu->flash_files[i].fragmented?emu->flash_files[i].pages[page]:emu->flash_files[i].offset+page*4096;
    mem_write32(&emu->mem,a[2],P1(phys+off));return 4096-off;
}
