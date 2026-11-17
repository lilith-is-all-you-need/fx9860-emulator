# 原生 Windows SuperH 预览与调试后端

本目录已实现可运行的 `FxEmulator.exe`，直接装载 `.g1a` 中的 SuperH 指令。没有将计算器源码重编译成 PC 程序。界面、数学计算和按键处理均由被加载的 G1A 执行。

2026-11-15 更新：新增 31 个 FX syscall 入口、默认故障留档后重建 HLE OS、可选保留现场
的暂停模式。完整范围与缺失项见 [系统调用覆盖和恢复说明](SYSCALL-COVERAGE.md)，
KhiCAS 的加载瓶颈见 [具体卡点与映射路线](../native-loader/KHICAS-BLOCKERS.md)。
这仍不是完整的 Casio OS 模拟。

2026-11-16 更新：加入可选的固件辅助 RAM 页表补页、碎片文件压力模式，以及
0x01E7 空闲/干净容器清理。Probe3 已在三个固件版本下完成整文件映射与交接测试；
Probe3 的 03.70.0200 实机回传已确认映射、回调和恢复检查通过。
参数、证据和未实现行为见 [OS 映射说明](OS-MAPPING.md)。

同日后续：补齐 0x0218 搜索槽位关闭，修正 FX Bfile 句柄的设备字节，
新增由 Probe3 地址确定的共存压力布局。完整的
[KhiCAS 专用 Loader](../mapped-loader/README.zh-CN.md) 已在模拟器完成启动、
计算、会话保存、菜单替换退出与新开实例；这不覆盖 MENU 后直接选回同一图标。
后续实机反馈首次启动可用，但直接选回卡住，完整生命周期验收仍未通过。

## 来源与结构

- 基础解释器：`third_party/emuCasioCalc`，上游 `https://github.com/joserodpt/emuCasioCalc`。
- 固定提交：`63e325708e9eea53eb4769b9c057082614ebd919`。
- 上游 MIT 许可证须随包保留；OS 文本使用的 Spleen / Unifont 字体许可证在上游 `assets/fonts/`。
- 使用 CPU、内存、SH7305、T6K11 以及系统调用模拟源码；没有链接 SDL 或 Casio 官方 SDK / OS 镜像。
- `prepare_sources.py` 在 `build/patched/` 生成调试钩子副本，并生成 `debugger-hooks.patch`。原上游源码不改动。
- `bridge.c` 实现仅监听 `127.0.0.1` 的 GDB Remote Serial Protocol 与控制协议；`bridge_platform.c` 提供显示、按键和字符适配。
- `compat.h` 适配 Windows 的 `mkdir`、`localtime_s`；`bridge_compat.h` 将路径统一视为 UTF-8，转成宽字符 `fopen`。

## 构建

运行 `build-bridge.ps1`。本机验证所用编译器为 MinGW GCC 15.1.0，路径 `C:\msys64\mingw64\bin\gcc.exe`。构建脚本需要 Python 3。启动已编译后端不需要 Python、MinGW 或 WSL。

输出为 `build/FxEmulator.exe`，当前带原生调试符号约 1.70 MB，动态导入仅有 Windows 自带的 `KERNEL32.dll`、`msvcrt.dll`、`WS2_32.dll`。编译过程使用相对 ASCII 源文件/输出路径，避免 MinGW 链接器对中文绝对路径的处理问题；用户运行时路径已用宽字符 API 实测。

## 运行协议

```text
FxEmulator.exe --gdb-port 0 --control-port 0 --framebuffer "绝对路径.bmp" "插件.g1a"
```

端口为 0 时自动分配。启动成功后 stdout 输出一行：

```json
{"event":"ready","gdbPort":12345,"controlPort":12346}
```

此时程序停在 `0x00300200` 的入口，模拟时间为零，尚未执行任何插件指令。GDB 应使用 `set architecture sh4al-dsp`、`set endian big`，随后连接所给端口，并载入与 G1A **配对**的未剥离 ELF。后端不负责加载 ELF 或猜测符号对应关系。

控制端口是持续 TCP 连接上的逐行 UTF-8 JSON，每请求返回一行 JSON：

```json
{"command":"status"}
{"command":"key","key":"EXE","down":true}
{"command":"key","key":"EXE","down":false}
{"command":"quit"}
```

状态包含 `state` (`paused` / `running` / `exited` / `error` / `rebooted`)、`pc`（8 位十六进制）、`cycles`、`reason`、`error`。支持的键名以 `src/utils/keys.c` 为准，包括数字、F1–F6、EXE、EXIT、MENU、SHIFT、ALPHA、AC、DEL、方向键、PLUS、MINUS、MULT、DIV、DP 等。未知键或未知命令返回 `ok:false`。

屏幕是 128×64、24 位 BMP，先写同目录临时文件再原子替换；运行时最多约 15 帧/秒。断点、单步或中断停下时，在发送 GDB 停止通知前强制读取并刷新当前硬件 framebuffer，不额外执行目标指令。UI 应打开并读取文件后立即释放文件句柄，以便原子替换。首次 continue 前不存在画面是正常的。路径不可写时后端启动失败，不宣称已 ready。退出时使用有界 socket linger，让最后的控制回复在 Winsock 清理前发送完毕。

## 调试语义

- 软件/硬件地址断点由解释器在执行目标指令前精确检查，不修改代码。
- 指令单步覆盖分支延迟槽；可在延迟槽内暂停、检查并恢复。处于延迟槽时改 PC 返回错误，以免破坏已锁存的分支目标。
- 读、写、读写观察点由实际访存钩子捕获，在该访存指令完成后报告。
- GDB 内存读取只读取普通映射页，不触发 MMIO，避免查看内存造成设备副作用；MMIO/未映射地址明确返回错误。
- 常用通用寄存器、控制寄存器及非活动寄存器银行可读写。不实现的 DSP/FPU 寄存器返回不可用值，而不是伪造为零。
- 暂停发生在同步调试事件泵中，保留解释器的 C 调用栈。因此可在 HLE 系统调用所执行的客户回调内暂停，不使用丢弃调用栈的长跳。
- 暂停不推进 CPU 周期/模拟时钟。异步 Ctrl-C 可以中断运行。
- 断开 GDB 会暂停目标并清理该连接的断点。所有监听均局限本机回环地址。
- 运行每片约 10ms，尽量贴近实时；并不声明周期精确或真实硬件速度精确。

## 已执行的验证

`test_bridge.py` 当前共 55 项集成检查通过，完整结果在 `build/bridge-test.json`：

- 使用包含中文和空格的 G1A 路径及 BMP 路径启动。
- 初始入口、寄存器包、内存访问、不可用 MMIO、非法断点错误。
- 真实 SH 指令执行、寄存器/内存写入、读/写观察点、延迟槽断点与恢复。
- 异步暂停、暂停时间冻结、键盘控制和正常退出。
- 错误校验和、溢出地址/长度、畸形内存写请求、重复 JSON 字段和非法控制消息的拒绝。
- 加载原始 CAS02 G1A，通过控制端口键入 `2+2`、按 EXE；得到 `=4`。最终屏幕前景像素与已经目视确认的独立执行结果逐像素一致。

`test_gdb.py` 使用本机真正的 `gdb-multiarch.exe` 连接后端，已验证反汇编、`stepi`、寄存器及内存修改、断点 continue、读/写观察点以及 `$r0==3` 条件断点。记录在 `build/gdb-real.log`。其中检查指令序列通过 GDB 写入目标模拟 RAM，测试的是 SH CPU 与 GDB 控制行为，不是 PC 函数。

`test_source_debug.py` 对 **CAS01 历史发布件**完成了源码层验证。`audit/compact-cas/target/khicas_next` 的三个非空 ELF PT_LOAD 段，与 CAS01 的 105,288 字节 G1A payload 全部逐字节相同，证据为 `build/cas01-pairing.json`。它不匹配 CAS02，因此没有混用。应用源码取自 CAS01 的发布快照。

该源码测试实际在 `main:62` 停住、读取 `key_options=468`、`next` 至第 63 行；在 `ui_draw:766` 停住、读取 `ui->input[0]=0` 和 `ui->notice="Starting CAS"`；调用栈显示 `ui_draw → main`；`next/step` 至第 767/772 行，`finish` 正确返回 `main:78`。完整输出见 `build/gdb-source.log`。此历史包使用 `-Os`/LTO，部分变量正常显示 `<optimized out>`；新项目应提供独立的 `-Og -g3` Debug 配置。Gint 库源码原路径不在该快照内，其源码行可能无法打开，但应用源码行可打开。

带调试钩子的 CPU 源码运行上游 `tests/test_cpu.c` 全部通过，覆盖除法、进位、call/延迟槽、循环、移位、乘法、DSP repeat、TRAPA/RTE 寄存器银行和 MOVUA。记录在 `build/test-cpu.log`。

`test_native_examples.py` 已对本次 **Windows 原生工具链新编译**的 `counter-c` 和 `counter-cpp` 的 Debug/Release 四份产物完成真实 G1A 执行验证。测试先核对构建 manifest 的 ELF/G1A SHA-256，再启动原生 GDB 16.3 与模拟器；没有回退到历史 KhiCAS 文件。

两种 Debug 版本均通过：main 断点、next 完成初始画面、真实 PLUS 键触发 change_counter 断点、参数 delta=1、C 指针/C++ 引用、局部 previous=0、step 进入 clamp_counter、三层调用栈、两次 finish 返回 main、寄存器和内存检查、counter.value=1 与 updates=1、更新后的屏幕。Release 版本通过入口断点、实际按键、原始内存状态及屏幕变化检查，不假称 Release 带应用 DWARF。共 18 组检查的结果、四份 MI 日志及四组初始/更新截图在 `build/native-examples/`；C++ Debug 更新画面已目视确认显示 Counter: 1、Updates: 1。

初始无调试探针 `preview-probe.exe` 还直接执行了 CAS02 的 106,568 字节 G1A：61,931,102 模拟周期、5 次显示更新、全部按键脚本步骤消费，无 CPU 错误。图像为 `build/initial.png` 和 `build/calculated.png`；正式后端截图为 `build/live-initial.png` 和 `build/live-calculated.png`。

## 2026-11 内存兼容与诊断增强

`calloc`（0x0E6B）和 `memmove`（0x0E6C）已补充。堆分配器检查乘法/对齐溢出、块边界、损坏的元数据、非法释放和重复释放；`realloc` 失败保留原块。此 HLE 对零长度分配返回 NULL，对非法释放报错，这些是模拟器的诊断策略，不宣称复现真机在未定义行为下的表现。

批量复制/填充先验证完整地址范围，失败时不部分写入；复制支持重叠、跨页和 P1/P2 别名，并触发观察点。补充 `Cursor_SetPosition`（0x0138）的边界和返回值、`Setup_GetEntry`（0x04DC）中 0x14 键盘状态项。其他设置索引仍明确报错。光标设置及查询现在保存并返回状态，但仍不画闪烁光标，调用跟踪标为 `partial`。

额外启动选项：

| 选项 | 用途 |
| --- | --- |
| `--trace-syscalls FILE.jsonl` | 每次调用的进入/完成、编号、名称、r4–r7、PR、SP、返回值和失败状态 |
| `--strict-stubs` | 遇到 `sc_nothing` 占位或已标记的 `partial` 实现立即报错；SetQuitHandler 已有回调实现 |
| `--fault-policy reboot/pause` | 默认记录并重建 HLE OS；pause 保留故障现场供 GDB 查看 |
| `--legacy-memory` | 对照旧版固定映射、无指令缓存/退出回调的模型，不用于 Loader 验收 |
| `--step-limit N` | 每次继续/单步后最多 N 次 CPU 执行钩子，含延迟槽；0 表示无限制 |
| `--heap-bytes N` | 缩小所选模拟堆，测试内存不足；至少 16 字节且为 8 的倍数 |
| `--memory-profile khicas` | 使用下表中的隔离布局，并检查每次指令前 SP 是否越界 |

`default` 仍是默认布局。`khicas` **是诊断配置，不是真机内存布局的测量结果**：

| 区域 | default | khicas |
| --- | --- | --- |
| HLE OS 堆 | `[88040000,88070000)`，192 KiB | `[88040000,8804C000)`，48 KiB |
| 栈顶 | `88080000`，不额外限制 | `88051000` |
| 检查的 SP 范围 | 无 | `[8804C000,88051000]`，20 KiB |

KhiCAS 样本自身使用 `88051000`、`88052000`、`[88053800,8807D000)` 等区域。默认布局可能重叠；隔离布局适合逐步排查。SP 检查不替代所有内存写入检查，也不会修复 guest 的 MMU/cache 操作。

新增控制请求 `{"command":"syscalls"}` 返回调用计数和最近 16 次调用；`{"command":"diagnostics"}` 返回内存配置、步数和模拟假设。`implemented` 仅表示有 HLE 处理函数，不能理解为完整 OS 实现；`stub` 专指 `sc_nothing`，`missing` 表示无对应处理。进入阻塞 GetKey 时 `completed:false` 是正常的等待。嵌套回调超过环形记录容量时，较早父调用的完成记录可能被省略，完整 JSONL 仍保留其进入记录。

默认启用功能级 UTLB/ITLB、指令缓存和退出回调，add-in 的 OS 原映射只读。
`functionalTlb:true`、`instructionCache:true`、`quitCallback:true` 表示这些路径已实现。
`realMmu:false`、`realOsExit:false` 仍保留：不运行完整固件的缺页/退出处理。
`copyBackDataCache:false` 表示数据缓存仍采用一致内存近似。未知系统调用停止执行；
严格占位检查也不能排除其他 HLE 函数中的简化。

独立复现与回归（普通 Python 3，无额外 Python 包）：

```powershell
./probes/emulator/test-runtime.ps1 -Python python
python probes/emulator/runtime_probe.py C:/samples/khicas.bin --output probes/emulator/build/sample --memory-profile khicas --steps 5000000 --timeout 3 --keys F1,2,PLUS,2,EXE
```

探针会输出 `report.json`、`syscalls.jsonl`、屏幕 BMP、每次按键前的 BMP 和 stderr；输入 `.bin` 只改扩展名即可。`--timeout` 是等待停止包的墙钟超时，之后发送 Ctrl-C；指令预算无法终止在宿主端等待按键的 HLE，因此应同时使用墙钟超时。按键自动化采用固定间隔，报告“sent”仅表示送出，需结合画面确认目标程序消费。

`test_runtime.py` 自行生成小型 SH/G1A，不依赖 KhiCAS 或官方 SDK。`test-runtime.ps1` 构建解释器并运行上游 CPU 测试、本地 13 组运行时测试和 15 组 `test_hardware.py` 硬件模型测试。GitHub 的 `Native emulator regression` 工作流执行同样检查，并运行原生 Loader 的 profile 测试。原有 `test_bridge.py` 55 项还依赖本机历史 CAS02 夹具，不放进公开 CI。

2026-11-15 本机验证：SHA-256 为 `4a9d1c18009d987dc7c8745b7fc099b3c6e8006ebbb2ee5e4b483934be757473` 的外部 KhiCAS 样本在两种布局均进入界面并显示 `2+2` 的结果 `4`；隔离布局下另走过除零、缺操作数、删除修改、EXIT/MENU 按键路径，无 CPU 错误或未知调用。MENU 按键测试不等于返回真实 OS 菜单。短路径通过不代表 KhiCAS 全功能或长期稳定；样本文件未纳入仓库。

语义核对来源：[fx legacy Setup](https://media.taricorp.net/prizm/simon_chm/fx_legacy_Setup.htm)、[fx legacy Cursor](https://media.taricorp.net/prizm/simon_chm/fx_legacy_Cursor.HTM)，以及本机 KhiCAS 关联源码的 syscall 桩。编号通过运行时实际调用核对，未据关联源码推定二进制完全同源。

## 2026-11-15 实机 Probe 反馈与 Loader Probe 2

本轮校正依据为用户回传的 Probe v1：数据已修改但旧指令仍执行，ICBI 后更新；
LDTLB 换页后数据侧切换而 ITLB 仍旧，单独失效 ITLB 后才执行新页；main 返回或
菜单切换后退出回调写入标记。注入 MENU 返回键值 30003，不触发实体菜单。
这些是实测现象；物理页、空闲槽号、URC/LRUI 动态值没有硬编码成该次快照。
HLE 声明的 OS 基线为此次的 `03.70.0200`，版本查询按实测输出 BCD 的
`03 / 70 / 0200 / 0000`，不再把次版本号误转为十进制数值；这不代表载入了该固件。

新模型提供 64 项 UTLB / 4 项 ITLB、1/4/64 KiB 与 1 MiB 页、V/D/ASID/共享位、
访问权限检查、LDTLB、URB/URC 和目标 TLB 失效。多重命中、未知临时页缺失和
权限错误停止执行。仅已知 OS 后备映射可由 HLE 重填；临时映射被替换后不会
偷偷从影子表复活。替换策略是可重复的功能近似，未实现完整异常向量或 OS 算法。
指令缓存为 16 KiB、4 路、32 字节行，写数据不会自动修改已有指令缓存。
GDB 普通内存读取跟随有效 UTLB，并支持 P2 别名，不产生缺页、MMIO 或缓存副作用。

`SetQuitHandler` 在主入口返回或模拟的菜单替换路径调用一次，清除旧注册后才执行
客户回调，回调错误可见。实体 MENU 在 GetKey 中进入 `status.osMenu:true`；
控制请求 `menu-resume` 恢复当前应用，`menu-replace` 调用退出回调并结束应用。
菜单等待中 EXE/EXIT 对应恢复，F1 对应替换。这不是完整 Casio 菜单或内置应用；
回调发生在“替换”时是目前的 HLE 策略，v1 记录不能确定实机的精确时刻。
随后 Probe 2.1 的菜单操作实机回传确认：GetKey 未返回时进入退出回调，目标
映射仍有效，回调内执行目标退出、恢复原映射、保存结果，之后重新启动。
其事件顺序与独立的 `menu-replace + reentry` 回归一致。该文件没有
`GETKEY_RESUMED`，因此不能把 `menu-resume` 分支或精确菜单触发时刻标为实机已验证。
OS 定时器在屏蔽中断时不运行，等待循环不会因到期但无法交付的定时器而死循环；
没有模拟每个硬件中断源的优先级和完整中断入口。

[Loader Probe 2](../hardware-loader/README.md) 使用独立 RAM 常驻代码、配套 BIN
与配置文件，测多页映射、资源/静态数据、OS 调用、定时器、退出/菜单恢复及持久日志。
它的模拟通过属于回归证据；两份 2.1 回传已确认所测 OS 调用、定时器、
直接退出与活动映射退出回调路径，范围及原始文件摘要见
[实机验证记录](../hardware-loader/VALIDATION.md)。不推广为任意 OS 调用或所有菜单行为的保证。
操作数 copy-back 缓存、DMA、总线写回时序、完整 OS 菜单/缺页仍未模拟。
尤其 `CCR=0x105` 的 CB 位为 1，不能把一次读到新数据解释为 write-through。
参考：[Renesas SH4AL-DSP 软件手册](https://www.renesas.com/en/document/mas/sh4al-dsp-software-manual)。

## 仍未覆盖的硬件行为

原生 Loader 集成测试补齐了 `GetKeyWait(menu=0)` 的矩阵 MENU 分支，以及
`Keyboard_ClrBuffer` 清除缓存但保留实体按住状态的行为。gint 使用定时器调用
`PutKeyCode(4,9,0)` 再等待这一接口；此前模拟器直接返回按键，使 Minesweeper
立即重启。现在进入已有 HLE 菜单，可选择恢复或替换。`PutKey(30003)` 注入返回码
仍原样返回，保留 Probe v1 的实测语义。这次矩阵路径的依据是 gint 的
`src/kernel/osmenu.c` 和 [Keyboard 接口文档](https://media.taricorp.net/prizm/simon_chm/fx_legacy_Keyboard.htm)，
尚不是新的实机测量结果。

[Native Loader](../native-loader/README.md) 已测试真实文件读取后的三个游戏启动。
Wolf 的 Quit 路径直接跳 `A0000000`，Fruit 的退出回调调用未知 `0x01E7`；
原程序直接启动也遇到相同阻断。两者未被填上假返回值，退出仍不算通过。

这是 GIII 类 SH7305/128×64 显示与部分系统调用的模拟器，并不是完整 Casio OS。采用上游 `MODEL_FX9750G3`（上游代码注明同属 fx-9860GIII / Graph 35+E II）。菜单内置应用、USB、DSP 算术指令等上游未模拟部分仍不可用；未知系统调用会报错。OS 文本替代字体可能与实机不同，gint 自带字体则由目标代码绘制。

“断点、变量、调用栈可用”与“所有硬件行为精确”是不同验收项。通过此处测试不等于所有 G1A、所有外设、所有 OS 版本或真机都已验证。原生工具链的 C/C++ 四种样例已单独通过上述验证；真机安装仍需实机验收。历史 CAS01 与本次新编译样例的证据分别保留。
# MENU resume stress (2026-11-17)

`--menu-vram-stress` redraws the OS VRAM when `menu-resume` returns from the
HLE menu. It can expose a stale OS loading screen hidden behind a guest-owned
display buffer. This is opt-in stress, not a validated full Casio menu model.
Resuming the same icon leaves GetKey/GetKeyWait suspended until an application
key arrives; it neither starts another add-in instance nor invokes quit cleanup.
`menu-replace` is a separate operation and invokes registered cleanup.
Hardware tests cover that distinction, redraw behavior, and the two real-device
RAM allocation rejections in the bounded `probe3` heap model. The reports alone
do not determine the actual device's free contiguous heap size.
