# FX 系统调用覆盖与故障恢复（更新于 2026-11-16）

累计增加 **34 个 FX 调度入口**（包括随后补充的 `0x02EE` 和部分实现的 `0x01E7`），并修正文件名转换、光标状态、故障现场保留和重启行为。
**没有完整实现 fx-9860GIII OS，也没有声称全部 syscall 已实现。**

## 检索范围与覆盖数字

主要依据 [Simon Lothar 的 FX 索引](https://media.taricorp.net/prizm/simon_chm/fx_legacy_syscalls.htm)
及其专题页；交叉检索 GIII、03.70，没有取得完整且经过验证的
GIII 03.70 ABI 定义。旧索引的号码范围是 `0x0000..0x1032`（4,147 个槽位），
其中有数据入口、异常处理入口和内置应用入口，不能全部当作普通 C 函数。

`syscall-catalog.json` 保存索引的事实性名称、引用和原始网页 SHA-256，排除
`0x0000 Name` 这种占位行；不包含 OS 固件或第三方 G1A。
`audit_syscalls.py` 从实际生成的 FX 调度表产生 `syscall-coverage.json`，CI 检查它没有过期。

| 类别 | 数量 | 含义 |
| --- | ---: | --- |
| HLE handler | 146 | 有执行代码；不代表全部语义、时序或实机等价已验证 |
| 部分实现 | 8 | 七个光标入口及 0x01E7 容器清理；尚有未实现路径 |
| 原有占位 | 6 | 重复按键 0x242/244/245/246、中断标志 0x3ED、电源 0x3F4 |
| 有名称/文档但未实现 | 247 | 包括内置应用、表达式求值、MCS 内部结构、通信协议、MMU/异常入口等 |
| 明确的数据入口、未实现 | 2 | 不能用空函数替代 |
| 未收录说明、未实现 | 3,738 | 不代表这些号码在真实 OS 中无效 |

实际 FX 调度表共有 **160 项**，旧索引去除占位后收录 **404 项**。
两项只在光标专题页定义的查询和已有 `0x1032` 键码表入口也纳入覆盖统计，因此不能直接用 160/404
声称完整支持率。号码范围本身也不保证覆盖 GIII 新增的入口。

## 新增与修正

KhiCAS 集成发现并修正 FX Bfile 句柄设备字节（fls0=01、crd0=02）；原小整数返回值让官方运行库错误地选择 MCS 保存路径。修改现有入口的 ABI，不另增加调度数量。依据本地 OS 042C 指令和真实 KhiCAS 调用链。

2026-11-16：进一步补充 `0x0218`，按九个固件分支的实际指令实现独立的四项搜索描述符清理。空闲/越界返回 -2，有效项只写入 0x0FFE 标记并返回 0；与普通 Bfile 句柄及 0x01E7 均不同。边界/标记/其余字节保留已与真实固件函数逐项对照。

2026-11-16：依据九个本地固件分支补充 `0x01E7` 的空闲及干净内部容器槽位清理。
它不是普通 Bfile Close，脏容器提交仍报错，详见 [固件映射与限制](OS-MAPPING.md)。

| 范围 | 本轮工作 | 依据 |
| --- | --- | --- |
| `0x2EE` | System_GetOSVersion 输出当前模型的版本字符串及 NUL；完整检查 11 字节输出范围 | [System ABI](https://media.taricorp.net/prizm/simon_chm/fx_legacy_System.HTM)、Ftune3 v2.40 的 Is35E2 调用 |
| `0x15F,161,162,163,172,173,18A` | atoi、定宽十六进制、大小写、忽略大小写比较、内存反转 | [索引](https://media.taricorp.net/prizm/simon_chm/fx_legacy_syscalls.htm)、[转换说明](https://media.taricorp.net/prizm/simon_chm/fx_legacy_LongToAscHex.HTM) |
| `0x2A1..2A4,2A7..2A9,467` | FX 十六进制返回约定、字符/字节/字转换、strlen 别名；LongToAscHex 补 NUL | [FX 转换 ABI](https://media.taricorp.net/prizm/simon_chm/fx_legacy_Converting.HTM) |
| `0x429,450,456,457` | 设备识别、宽文件名长度、双向转换；识别 0/FFFF 终止并按 n 补齐，保留低字节 | [Bfile](https://media.taricorp.net/prizm/simon_chm/fx_legacy_Bfile.htm) |
| `0x531,533,534,536..538,53C..53E,541` | 多字节字符识别/计数/复制/拼接/堆复制、itoa；保留 MB_strncat 返回源地址的约定 | [MultiByte](https://media.taricorp.net/prizm/simon_chm/fx_legacy_mb.htm)、索引 |
| `0xE6E,E6F` | strchr、strstr，包括 NUL、空串、找不到及错误地址 | 索引、C 字符串约定 |
| `0x139..13B,80E,80F,811,812` | 替换无状态光标空实现；新加两项查询，仍明确标为 partial | [Cursor](https://media.taricorp.net/prizm/simon_chm/fx_legacy_Cursor.HTM) |
| `0x236`、执行到 `A0000000` | 记录为显式重启请求，使用统一恢复流程 | 索引 RebootOS；Wolf 指令路径与用户实机反馈 |

公开资料也有矛盾：RTC 索引写 1/64 秒，[RTC 专页](https://media.taricorp.net/prizm/simon_chm/fx_legacy_RTC.htm)
写 1/128 秒；本轮没有仅凭索引改动已有 1/128 模型。MB 页面示例中的 E8 也与其
明确列举的 lead-byte 集合不一致，本实现采用明确列举的集合；仍需要真机边界验证。
LongToAscHex 当前只接受 0..8 位，越界报错；历史返回寄存器不是稳定 API 保证。
ASCII 大小写、畸形多字节串、整数溢出等不能据本轮单元测试推出真实 OS 的未定义行为。

## Ftune3 与 0x02EE 补充验证

`void System_GetOSVersion(unsigned char *version)` 输出 `MM.mm.ssss` 格式的
10 个 ASCII 字符以及结尾 NUL，共 11 字节；当前 GIII 模型为 `03.70.0200`，
与 `0x0015` 及模拟 ROM 头共享版本来源。文档的“10 characters”指可见文本，
ASCIIZ 还需要终止字节。无文档定义的返回值；不要依赖 HLE 内部的 r0=0。
非法/只读/MMIO/跨 RAM 末端的输出地址会触发诊断，且范围检查失败不会先写入前半段。
此失败策略不宣称复现真实 OS 对非法 C 指针的行为。

Ftune3 v2.40（57,676 字节，SHA-256
`4ddb90f3ffaff961d21bf87ebb48b24062a00b952f4ba872845a4539f24d69bd`）
直接启动和经原生 Loader 启动均越过版本查询，进入主界面，执行 F2 预设及 F1 默认预设，
通过程序自己的寄存器显示页观察 FRQCR 从 `0F102203` 变为 `0F112213`。
未编辑客户寄存器/内存，BIN 与原 G1A 字节一致；Loader profile 修改其已识别 syscall 跳板。
11 月 15 日 MENU 后替换应用，两条路径均在未知 `0x01E7` 留档重启。
11 月 16 日重测已越过四次空闲容器清理，随后在未实现的 `0x0218` 留档重启。
因此调频操作路径已有模拟执行证据，完整退出和实机超频稳定性仍未通过。
首次运行还会显示配置读取提示；配置持久化和内存测速未在这次验证范围内。

## 默认恢复行为

命令行默认 `--fault-policy reboot`。未知 syscall、未处理的 CPU/MMU 错误、
退出回调失败和配置的栈越界都会先保存现场，然后建立全新的 HLE 机器状态。
这清理 RAM、TLB、指令缓存、堆、打开文件、定时器和退出回调，保留磁盘上的存档。
不调用可能已损坏的旧退出回调。正常返回和正常菜单替换仍按正常退出处理。

重启后状态为 `rebooted`，屏幕显示报告已保存和 EXE 重载提示。等用户按 EXE、
控制命令 `launch` 或 GDB continue 才运行入口，避免自动重复触发同一故障。
经 Loader 运行目标时，重新启动的是原 `Loader.g1a`，不是绕过 Loader 直接启动目标。

这是一套 **HLE OS 状态重建**，不是执行 Casio 固件的真实开机过程。
它复现本轮要求的故障恢复策略，并不声称真机所有异常都以相同方式重启。

每次故障在 framebuffer 旁生成唯一文件名的三个文件，不覆盖上一份：

- `.fault-…json`：原因、CPU 寄存器、访存错误、最近 64 个指令地址、64 UTLB/4 ITLB、
  有效指令缓存行和最近 16 次 syscall。`reset-vector`、`syscall-0236`、
  `unexpected-fault`、`debugger-reboot` 分开记录。
- 同名前缀 `.ram.bin`：重启前 512 KiB RAM 原始字节，物理起点 `0x08000000`。
- 同名前缀 `.bmp`：重启前画面；stderr 和可选完整 syscall JSONL 日志继续保留。

报告是故障分析资料，不是可直接恢复执行的完整 save-state；未保存所有外设内部状态。
如报告写入失败，停止在 `report-failed` 并保留内存；如原 G1A 无法重载，停止在
`reload-failed` 并保留旧机器与已写报告。主机进程自身崩溃、系统断电、程序无限循环
不在自动 guest 异常恢复的覆盖范围内；循环仍可用中断和 `--step-limit` 调试。

## 调试与协议

`--fault-policy pause` 保存报告后停在原故障现场，保留连接、寄存器和内存。
`runtime_probe.Session` 默认为此诊断策略；其 `fault_policy=None` 使用命令行默认。
`--strict-stubs` 同时拒绝已知空实现和 partial 光标/容器实现，避免拿占位行为作验收依据。
缺失的调用在任何模式下都报错；不会为了让测试通过而静默返回成功。

```json
{"command":"recovery"}
{"command":"reboot"}
{"command":"launch"}
```

`recovery` 返回策略、重启次数、报告路径和是否等待启动；`reboot` 只在暂停/停止时接受，
回调内部暂停也可请求，待 C/guest 调用栈退出后才释放机器；`launch` 只在恢复页接受。
调试器断点继续保留。故障 syscall 的 PC 不再被无条件改成 PR，便于定位。

## 验证范围

本轮通过 CPU 原有回归、13 组运行时、15 组硬件模型、10 组新增 FX ABI、
12 组恢复测试、55 项协议/实际 G1A 检查，以及 8 组 Loader profile 测试。
恢复覆盖显式重启、未知调用、非法指令、MMU 错误、退出回调错误、GetKey 内暂停重启、
连续故障不覆盖报告、句柄/定时器清理、存档保留、写报告失败及重载失败保留现场。

四个原始样本均重跑，详见 `VALIDATION-2026-11-15.json` 与
`../native-loader/KHICAS-BLOCKERS.md`。Wolf 与 Fruit 的重启是恢复验证成功，
不能算成正常退出兼容成功；KhiCAS 经 Loader 仍在交接前拒绝。

真实 Windows GDB 的单步、反汇编、条件断点和读写观察点也通过。旧脚本首次运行
超时：它在已经执行过的缓存页内重写测试指令，没有 ICBI，实际读取到缓存中的旧零值
并触发故障。测试夹具改为 P2 非缓存 RAM 后通过；没有删除或绕过被测指令缓存模型。
调试器修改代码内存本身不隐式刷新客体缓存，缓存一致性仍由专门硬件测试覆盖。
