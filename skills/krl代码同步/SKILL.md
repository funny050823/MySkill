---
name: krl代码同步
description: 把 KRL 复刻解析器(KRL::ReadFile)与引擎原函数(KGRLLoader::LoadUnitFromFile)对齐,修复"复刻落后引擎"导致的 .krl(角色外观)解析失败/漏抽依赖路径。当用户提到 krl 解析失败、角色外观解析失败、KRL 复刻落后引擎、KGRLLoader/KGRLFileType 对齐、KGRL V0-V5 新版本未同步、krl 漏抽依赖路径(mesh/mtl/ani/portrait)、或想让 KResourceReader 正确解析新版本 .krl 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到差异清零且无意外差异为止。
---

# KRL 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `KRL::ReadFile`(`kg_krl::KRL`)是引擎 `KGRLLoader::LoadUnitFromFile` 的**复刻**,解析 `.krl` 角色外观文件。`.krl` 描述一个角色的单位属性(UnitProperty:主模型/肖像)、插槽 socket(各 slot 的 mesh/mtl)、动画(animation:各 ID 对应 .ani)、随机动画/动画融合。复刻只"读得动 + 抽资源检查需要的依赖路径",不跑外观逻辑。

引擎用**文件头 `version` 字段**把 `.krl` 分成 V0-V5 六个版本(`KGRLFileType` 枚举),每个版本一个 `LoadUnitFromBufferV*` 函数,各自的结构体布局不同(每升一版改字段/改 pack/加参数)。复刻一旦没跟上引擎新增的 V6+,或某版本结构体字段没同步,遇到新版本的 `.krl` 就会**解析失败**或**漏抽依赖路径**——典型如引擎加 `V5`(Add bCompletePlayOnStateUpdate to animation)时复刻没跟,含该版本动画的 .krl 错位。

⚠️ **与 Pss 的关键差异(决定技能不同)**:
1. **只抽一类:明文依赖路径**(mesh/mtl/ani/portrait),经 `OnUnitProperty`/`OnAnimation` 回调内部转 `OnReadResourceFileByGBK` 登记。**没有音频标签**(不跑 `KSearchResource.exe SearchAudioLabel`,无 AudioLabel.db)、**没有数值汇总**(无 PssInfo 那样的包围盒/粒子数,别找第三类)。同 Ani 的"无音频"形态,但 krl 的依赖路径很多(每版本函数都抽)。
2. **调用路径同 kmsc**(reader 工厂):`AddFileType("krl", &ProcessKrl)`(`Jx3ResFileReaderAPI.cpp:119`)→ `ProcessKrl` → `new kg_krl::KRL` → `KRL::ReadFile`。
3. **结构自维护**:`KGRLFormat.h`/`KGRLDefine.h` **自维护** `KGRLFileType` 枚举(V0=1..V5=6 + Max)、`KGRL_FILE_HEADER_EX`、各版本 `KGRL_FILE_*_V*` 结构(非 include 引擎头,同 Ani 的 `Ani.h`)——落后风险在**枚举值/结构体大小/各版本函数**,不在 include 同步。⚠️ 引擎的 `KGRLFormat.h` 经 `SO3Represent/RLFile/KGRLFormat.h` include 路径解析,本机未必能直接 Read 到该头(可能解析到生成/发布目录);比对时以引擎 `KGRLLoader.cpp` 里对结构的字段访问反推字节数,与复刻 `KGRLFormat.h` 副本逐一核对。
4. **顶层 `default` 软失败**:复刻 `switch(version)` 的 `default` 调 `OnErrorByGBK(ERROR_LEVEL_TOOL_ERR, ERROR_TYPE_OLDER_KRL, "工具支持解析的krl最新版本号是%d,本文件版本号%I64u", Max-1, version)`——**不硬失败**(不像 kmsc 的 NewAction),只报"工具版本太老",该 .krl 跳过该版本、不抽但不挂。落后多表现为"漏抽/版本外",少表现为"解析失败"。

本技能把"对齐复刻与引擎"做成**全自动闭环**(同 Pss/kmsc/Ani):比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 有意外差异就回滚,直到差异清零。过程中**守住一类信息抽取口径**(明文依赖路径)。

> 工作模式:**全自动闭环**(同 Pss/kmsc/Ani),中途不必征询用户,收尾汇报。护栏见 §7。仅在 windows 下执行。

---

## 1. 锁定路径（别取错）

> **前置环境检查(同 Pss,进技能第一步先做,缺了直接报错、不继续)**:本技能依赖一组 Windows 环境变量(系统配置,非会话临时设),编译/对标都要用。进 §7 闭环 A 步前,先逐个核实存在:
> | 环境变量 | 必需 | 用途 | 缺失后果 |
> |---|---|---|---|
> | `JX3ENGINE_Sword3` | **必** | 引擎源码根(`...\Source\...`),对标口径 + 编译 include/lib | 找不到引擎文件、编译失败 |
> | `JX3ENGINE_BASE` | **必** | 编译 include/lib(`$(JX3ENGINE_BASE)\include` 等) | 编译失败 |
> | `JX3ENGINE_DevEnv` | **必** | 部分工程编译用(`$(JX3ENGINE_DevEnv)/Include` 等) | 编译失败 |
> | `JX3_HD_Client` | **必** | client 测试数据根(全量扫描输入),指向 client 数据根目录(sword3-products 下的 client 副本),内容以 GB 计、不会为空 | 全量扫描无数据 |
> | `MSBuildTool` | **必** | MSBuild.exe 路径(编译 `FileParse.sln`),指向 `...\2019\...\Bin\MSBuild.exe` | 编译失败 |
> | svn `wc.db` | **必** | `$JX3_HD_Client/../.svn/wc.db` 或 `$JX3_HD_Client/.svn/wc.db` 之一(exe 要求 `PathFileExistsA(pszDBFile)` 真) | 扫描器报"参数错误" |
> - 检查命令(bash,同 Pss):`for v in JX3ENGINE_Sword3 JX3ENGINE_BASE JX3ENGINE_DevEnv JX3_HD_Client; do [ -d "${!v}" ] && echo "$v OK=${!v}" || echo "$v 缺失/无效,技能终止"; done; [ -f "$MSBuildTool" ] && echo "MSBuildTool OK=$MSBuildTool" || echo "MSBuildTool 缺失/无效,技能终止"; WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"; [ -f "$WCDB" ] && echo "wc.db OK=$WCDB" || echo "wc.db 异常,技能终止"`
> - 任一**必需**项缺失 → 报错并停止。

> **项目路径(仓库根)**(同 Pss):`KResourceReader` 仓库根 = 本 SKILL.md 上溯 4 级 = Claude 执行技能时的工作目录(Primary working directory)。说明路径写作 `项目路径\...`;bash 命令块用 `REPO="$(pwd -W)"`(Windows 绝对,exe 能接受),块内 `$REPO/...`;传 exe 的文件路径必须绝对(exe 内部 `SetCurrentDirectoryA` 到 client,相对路径失效)。Claude 执行技能 cwd 本就在仓库根,`pwd -W` 直接对。

复刻侧（你要改的，UTF‑8，Edit/Write 安全）:
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`KRL.cpp` 编进此工程,以 `..\src\krl\KRL.cpp` 引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\krl\KRL.cpp`（顶层 `ReadFile` + 各版本 `LoadUnitFromBuffer`/`..V1`..`V5` + 抽取回调 `OnUnitProperty`/`OnAnimation`,**117KB,主要落点**)
- `项目路径\src\krl\KGRLFormat.h`（**自维护** `KGRLFileType` 枚举(V0=1..V5=6+Max) + `KGRL_FILE_HEADER_EX` + 各版本 `KGRL_FILE_*_V*` 结构,非 include 引擎——落后风险在枚举值/结构大小/各版本函数,同 Ani 的 `Ani.h`)
- `项目路径\src\krl\KGRLDefine.h`(`RL_FILE_IDENTIFIER`('RL00') 等宏、`RLNPC_TYPE`/`CHARACTER_SHOW_LEVEL` 等枚举)
- `项目路径\src\krl\KRL.h`(`KRL` 类 + `LoadUnitFromBufferV1..V5` 声明 + `m_listKRL`/`m_setSlotName`)
- 若上面不存在,从本 SKILL.md 目录上溯 4 级再下 `src\krl`:`%cd%\..\..\..\..\src\krl\KRL.cpp`(`%cd%` 指本 SKILL.md 目录,非 CodeReviewKrl.md 目录)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\Common\SO3Represent\SO3Represent_2019.vcxproj`(`KGRLLoader.cpp` 在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\Common\SO3Represent\Src\base\RLFile\KGRLLoader.cpp` 的 `KGRLLoader::LoadUnitFromFile`(`:561`,读 `KGRL_FILE_HEADER_EX` → 校验 `identifier==RL_FILE_IDENTIFIER` → `switch(version)` 分派 V0-V5 到 `LoadUnitFromBuffer`/`..V1`..`V5`,`default` `RLError("Unknow RLFile Version")` 返回 null)
- **per‑version 读取(逐版本同步的真正落点)**:`KGRLLoader.cpp` 各 `LoadUnitFromBufferV1`(`:883`起)/`V2`/`V3`/`V4`/`V5`,每个版本读不同结构布局。**各版本结构体差异都在这里**(§2.2)。
- **结构/枚举口径**:引擎 `SO3Represent/RLFile/KGRLFormat.h`(经 include 路径解析,本机未必能直接 Read;以 `KGRLLoader.cpp` 字段访问反推字节数,与复刻 `KGRLFormat.h` 副本核对)。`KGRLFileType` 枚举(V0=1..V5=6)两侧同名,version 字段写盘值即枚举值。
- **读写基准**:`KGRLLoader.cpp` 里写盘相关逻辑(各版本 `LoadUnitFromBufferV*` 末尾 `pUnit->Header.fccVersion = static_cast<int>(KGRLFileType::Vx)`)反推 reader 字节数。

对标源总览:
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层分派 | `KGRLLoader::LoadUnitFromFile`(`KGRLLoader.cpp:561`) | `KRL::ReadFile`(`KRL.cpp:75`) |
| 文件头校验 | `identifier==RL_FILE_IDENTIFIER`、`switch(version)` | 同(`KRL.cpp:91-94`) |
| V0 | `LoadUnitFromBuffer`(`:639`) | `KRL::LoadUnitFromBuffer`(`KRL.cpp:125`) |
| V1 | `LoadUnitFromBufferV1`(`:883`) | `KRL::LoadUnitFromBufferV1`(`KRL.cpp:391`) |
| V2 | `LoadUnitFromBufferV2`(`:1191`) | `KRL::LoadUnitFromBufferV2`(`KRL.cpp:655`) |
| V3 | `LoadUnitFromBufferV3`(`:1479`) | `KRL::LoadUnitFromBufferV3`(`KRL.cpp:927`) |
| V4 | `LoadUnitFromBufferV4` | `KRL::LoadUnitFromBufferV4`(`KRL.cpp:1223`) |
| V5 | `LoadUnitFromBufferV5` | `KRL::LoadUnitFromBufferV5`(`KRL.cpp:1536`) |
| 枚举 | `KGRLFileType`(V0=1..V5=6+Max,引擎 `KGRLFormat.h`) | `KGRLFormat.h` `KGRLFileType` 副本(自维护) |

> **krl 调用路径(同 kmsc,reader 工厂分派)**:`Jx3SvnHookCheckTool.exe` → `Jx3ResFileReaderAPI`(reader 工厂按扩展名分派)→ `ProcessKrl`(`Jx3ResFileReaderAPI.cpp:273`,`return new kg_krl::KRL()`)→ `KRL::ReadFile`。`AddFileType("krl", ...)` 在 `Jx3ResFileReaderAPI.cpp:119`。依赖路径经 `OnUnitProperty`/`OnAnimation` → `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

---

## 2. 差异比对法（每轮第一步）

引擎 `LoadUnitFromFile` 读 `KGRL_FILE_HEADER_EX(identifier, version, ...)` → 校验 `identifier==RL_FILE_IDENTIFIER`('RL00')→ `switch(pFileHeader->version)` 按 `KGRLFileType` 分派到 `LoadUnitFromBuffer`/`..V1`..`V5`,`default` `RLError` 返回 null。复刻 `KRL::ReadFile` 同构(`KRL.cpp:91` 读 header → `:92` 校验 identifier → `:94` switch version V0-V5 → `default` `OnErrorByGBK(ERROR_TYPE_OLDER_KRL)` 软失败)。

⚠️ **差异重点有两个,缺一不可**:
1. **版本层**(`version` switch,§2.1)——新增 `KGRLFileType::V6+`。这是 krl 最核心的落后风险点:引擎每加一版(V6、V7...)就加一个 `LoadUnitFromBufferV6`,复刻 `switch` 没跟 → 含新版本的 .krl 落 `default` 报 `ERROR_TYPE_OLDER_KRL`、漏抽(不挂,但该 .krl 依赖全丢)。
2. **per‑version 结构层**(§2.2)——每个 `LoadUnitFromBufferV*` 内部读各自的结构布局(`KGRL_FILE_*_V*`),引擎改某版本结构字段/大小(pack、加参数)而复刻 `KGRLFormat.h` 副本没跟 → 该版本 .krl 字段错位、依赖路径读错位/漏抽(最隐蔽,不报错但读错)。

⚠️ **比对口径关键:区分"字节布局差异"与"运行时逻辑差异"**(同 tani/Pss/Ani):
- **字节布局差异**(改变 `Reference`/读多少字节):复刻**必须对齐**——结构字段/大小/读取顺序不一致,后续错位。这是 §2.2 比对重点。
- **运行时逻辑差异**(读了字段后做运算/设运行时状态,不改字节):复刻只抽路径、不跑外观逻辑,**不需要同步**——如引擎算插槽变换矩阵、动画融合权重,复刻用 `Reference` 读过/`SkipData` 跳过即可,不算落后。
- **判定法**:看该差异是否改变"读了几个字节/按什么结构读"。改变字节=要对齐;只改运行时行为=复刻跳过即可。

### 2.1 版本层(`KGRLFileType` / `version` switch)
- 枚举全集:复刻 `KGRLFormat.h:35` `enum class KGRLFileType { V0=1, V1=2, V2=3, V3=4, V4=5, V5=6, Max }`。逐项核对值(枚举值写进文件 `version` 字段,错位读错版本)。
- 引擎 `KGRLFileType`:在引擎 `KGRLFormat.h`(经 include 解析)。两侧同名常量、`switch` case V0-V5 全一致(已核实:`KGRLLoader.cpp:599-619` 与 `KRL.cpp:96-112` 一一对应)。
- 复刻 `switch(version)`(`KRL.cpp:94`):case V0-V5 + `default` `OnErrorByGBK(ERROR_TYPE_OLDER_KRL)` 软失败。
- 差集:引擎有 `V6+`、复刻 `switch` 缺 = **候选同步项**。复刻 `default` 软失败——引擎新增版本且写进 `.krl` 时,含该版本的 .krl 落 default 报 `ERROR_TYPE_OLDER_KRL`、漏抽该 .krl 全部依赖(不挂,但 Result 里该 .krl 无依赖记录、可能 `still_failing` 外另有"扫到但无依赖"的异常)。
- ⚠️ **"switch 缺 V6+" ≠ "必须立刻同步"**:先核实该版本是否真被**写进 `.krl`**(看引擎 `KGRLLoader.cpp` 是否有对应 `LoadUnitFromBufferV6` 的 reader,以及编辑器/`SaveUnitToFile` 是否产出该版本)。引擎有 reader = 会写盘 = 要同步。
- 对每个确认要同步的新版本:去引擎 `KGRLLoader.cpp` 找 `LoadUnitFromBufferV6`,**按字节顺序**把读取序列搬进复刻(在 `KRL.cpp` 加 `LoadUnitFromBufferV6` + `ReadFile` switch 加 `case V6` + `KGRLFormat.h` 加 `KGRLFileType::V6=7` 常量与该版本结构体),套用复刻现有版本函数风格(`Reference` 直读结构 + `OnUnitProperty`/`OnAnimation` 抽依赖)。

### 2.2 per‑version 结构层（重点,遍布各版本）
每个 `LoadUnitFromBufferV*` 内部读各自版本的 `KGRL_FILE_*_V*` 结构。逐版本两侧结构布局比对:
| 版本 | 引擎结构(以 cpp 字段访问反推) | 复刻结构(`KGRLFormat.h`) | 比对要点 |
|---|---|---|---|
| V0 | `KGRL_FILE_HEADER_EX` + `KGRL_FILE_STRINGTABLE` + `KGRL_SOCKET` + `KGRL_FILE_UNITPROPERTY` + `KGRL_FILE_ANIMATION` + `KGRL_FILE_RANDOMANIMATION` + `KGRL_FILE_ANIMATIONFUSION` | `KGRLFormat.h` 对应结构 | 字段/大小/pack 一致 |
| V1 | `..._V1` 系列(`KGRL_FILE_HEADER_EX_V1`/`KGRL_FILE_SOCKET_V1`/`KGRL_FILE_UNITPROPERTY_V1`/`KGRL_FILE_ANIMATION_V1`/...) | 同名副本 | V1 是 x64,pack 与 V0 不同,逐字段核 |
| V2 | pack(1) 优化 | 同名副本 | V2=pack(1),V1 工具是 pack(8)——pack 差异易错位 |
| V3 | Optimize socket content file size | 同名副本 | socket 结构缩小 |
| V4 | Add body reshaping param field | 同名副本 | UnitProperty 加字段 |
| V5 | Add bCompletePlayOnStateUpdate to animation | 同名副本 | Animation 加字段 |
| 文件头 | `KGRL_FILE_HEADER_EX`(identifier+version+oftUnitProperty+animationCount+oftAnimations+socketCount+oftSockets+...)| `KGRLFormat.h:46` 同 | 各 offset 字段一致 |

- **比对法**:对每个版本,读引擎 `KGRLLoader.cpp` 该版本函数里 `Reference`/读结构的 `sizeof(...)` 与字段访问顺序,反推该版本字节数;再读复刻 `KGRLFormat.h` 对应 `KGRL_FILE_*_V*` 结构的 `sizeof`(pack 后),与复刻 `KRL.cpp` 该版本函数的 `Reference(sizeof(...))` 逐一核对。**字段数/顺序/大小任一不一致 = 错位,要同步**。
- ⚠️ **pack 差异最隐蔽**:V2=pack(1)、V1 工具=pack(8),结构体 `#pragma pack` 不一致会改变 `sizeof`。复刻 `KGRLFormat.h` 各版本结构的 pack 必须与引擎该版本一致(以 cpp 反推为准)。

> 实操:grep 各取两侧 `KGRLFileType::V`/`case static_cast<int>(KGRLFileType` 做 switch case 集合差(§2.1);对每个版本,grep `KGRL_FILE_.*_V` 结构名两侧比对字段/大小(§2.2),用引擎 `KGRLLoader.cpp` 各 `LoadUnitFromBufferV*` 的 `Reference(sizeof(...))` 反推字节数与复刻 `KRL.cpp` 同版本函数逐一核对。区分"字节布局差异"(要对齐)与"运行时逻辑差异"(复刻跳过即可)。结论写进当轮记录(改了哪个版本/补了哪个结构/对应引擎文件:行)。

### 2.3 文件头/枚举常量
- `RL_FILE_IDENTIFIER` = `'RL00'`(四字符码),两侧一致(`KGRLDefine.h:13`)。
- `KGRLFileType` 枚举值 V0=1..V5=6 写进 `version` 字段,复刻副本与引擎同名同值。
- `KGRL_FILE_HEADER_EX` 文件头结构(identifier+version+各 offset+count)两侧字段一致,否则 `Reference(sizeof(KGRL_FILE_HEADER_EX))` 读的长度错、后续全错位。

---

## 3. 一类信息抽取（同步时的不变量，必须守）

⚠️ **krl 只抽一类:明文依赖路径**。**没有音频标签**(不跑 `SearchAudioLabel`,无 `AudioLabel.db`)、**没有数值汇总**(无 PssInfo 那样的汇总结构,别找第三类)。`KRL` 的 `m_listKRL`/`m_setSlotName` 是内部收集(slot 判断用),不入库、不参与前后对比。同步任何新版本/结构时,依赖路径抽取**必须跟着补**。**口径以宏为信号,宁多勿漏**:凡是 `OnUnitProperty`/`OnAnimation` 回调里带路径的参数(`pszMainModelFile`/`pszMeshFilePath`/`pszMtlFilePath`/`pszAnimationFile`/`pszPortrait`),经内部 `OnReadResourceFileByGBK` 登记为依赖,一律捞,不靠字段名过滤。

### 3.1 明文依赖路径（`OnUnitProperty` / `OnAnimation` → `OnReadResourceFileByGBK`）
登记接口:`OnReadResourceFileByGBK`(扫描时落 `ScanResult.db` 的 `Result` 表,`SonFile`/`SonExtName` = 依赖,`File` 以 `.krl` 结尾)。复刻经两个回调登记:
| 回调 | 抽的路径 | 大致落点 | 备注 |
|---|---|---|---|
| `OnUnitProperty(sidxMap, sidxName, sidxMainModelFile)` | 主模型 `pszMainModelFile` | `KRL.cpp:1849` | slot 名是数字时记 `m_listKRL`(对应另一个 krl),否则登记路径 |
| `OnUnitProperty` 还登记 | socket 的 `pszMeshFilePath`/`pszMtlFilePath`、肖像 `pszPortrait` | 各版本函数内(`:236`等) | slot mesh/mtl/portrait |
| `OnAnimation(dwAnimationID, psidxAnimationFile)` | 动画文件 `pszAnimationFile`(.ani) | `KRL.cpp:1875` | 每 animation ID 一个 |
| `OnAnimation(dwAnimationID, sidxName, pszMeshFilePath)` | 动画 socket 的 mesh/mtl | `KRL.cpp:1906` | 随机动画/socket 引用 |

各版本函数抽取点(每版本都抽,`OnUnitProperty`+`OnAnimation` 调用数):
| 版本函数 | OnUnitProperty | OnAnimation | 直接 OnReadResourceFileByGBK |
|---|---|---|---|
| `LoadUnitFromBuffer`(V0) | 4 | 3 | 0 |
| `..V1` | 4 | 3 | 0 |
| `..V2` | 3 | 4 | 0 |
| `..V3` | 3 | 4 | 0 |
| `..V4` | 3 | 4 | 0 |
| `..V5` | 4 | 6 | 3 |

> 实测依赖类型分布(mesh/mtl/ani/portrait):同步新版本时对照分布,看该抽的路径抽没抽到。`.krl` 依赖落 `Result` 表(同 kmsc/tani),`SonExtName` 多为 `mesh`/`mtl`/`ani`/`portrait` 等。

> 每轮同步后,逐版本自问:这个新版本/结构的路径读取登记依赖了吗?(krl 无音频、无数值汇总,只这一类。)

---

## 4. 构建（同 Pss）

编译整个解决方案产出扫描器(`Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- `KRL.cpp` 在 `Jx3ResFileReaderAPI.vcxproj`。
- **前置:先编译 RUST 依赖工程(同 Pss §4,稳妥起见)**:`Jx3ResFileReaderAPI.vcxproj` link 依赖 `ClipLibX64.lib`/`KESMBaseX64.lib`(import lib),但 `FileParse.sln` 不含这两个工程、不会自动先编。lib 缺失/过期/换机器未编 → 链接 LNK1104。每轮先编:
  ```bash
  # bash 下 / 写成 //;dos/cmd 写 /p:
  "$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
  "$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
  ```
- MSBuild:用 `%MSBuildTool%`(见 §1)。命令(在仓库根,用相对 `FileParse.sln`):
  ```bash
  "$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
  ```
  - bash 下 MSBuild 的 `/` 参数写成 `//`(防 bash 当成路径)。
- **不要用 `Build.cmd`**(带 svn up/git 推送/PE 核验副作用)。本闭环只要 `FileParse.sln` rebuild 出新 exe。
- 判定:退出码 0 且 `x64\Release\Jx3SvnHookCheckTool.exe` 更新时间刷新即成功。编译失败 → 看 MSBuild stdout 先修编译错。
- ⚠️ 编译遇 LNK1104 打不开 dll/exe → 多半有遗留 `Jx3*` 工具进程锁着,`tasklist | grep Jx3` 查、`taskkill //PID //F` 结束后重试(也可能是 RUST lib 没编,见上"前置")。

---

## 5. 测试（全量）

全量 = 深扫 `$JX3_HD_Client\represent\rl\` 下所有 `.krl`(本机约 **7.7 万**个,按 `00000000/00000000.krl` 哈希目录存;实测约十几秒/轮——扫描只读头部+按存盘长度跳字节、不 cook、多线程,不慢)。

### 5.1 生成扫描清单(GBK!)
`ScanFileList_krl.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 写**(UTF‑8 破坏中文)。用脚本(与 Pss/kmsc/Ani/tani 共享的通用脚本):
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
# ⚠️ REPO 必须从仓库根(KResourceReader)取,勿在 x64/Release 里用 cd .. && pwd -W 取——cd .. 只退到 x64 一级,pwd -W 得到 仓库根/x64(多了一个 x64 段,即多一层),再拼 $REPO/x64/Release/logs/ScanFileList*.txt 就成了 仓库根/x64/x64/Release/logs/ScanFileList*.txt(x64 重复、文件不存在)→KResScanMgr::MainScan GetLastError(3) 扫0文件、45ms 退出。cwd 在仓库根时 pwd -W 直接对,无需 cd。
python "$REPO/.claude/skills/krl代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/represent/rl" --ext krl \
  --out   "$REPO/x64/Release/logs/ScanFileList_krl.txt"
```
(krl 用独立清单 `ScanFileList_krl.txt`,避免与其他技能清单互相覆盖。`--root "$JX3_HD_Client/represent/rl"` 深扫 krl 目录。)

### 5.2 跑扫描器(关键:ReadFileListFromSvnDB=1)
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO/x64/Release"
# svn wc.db:client 上级是副本根→../.svn,自身是副本根→.svn,两者必须存在一个(§1 前置已查,此为兜底)
WCDB="$JX3_HD_Client/../.svn/wc.db"
if [ ! -f "$WCDB" ]; then WCDB="$JX3_HD_Client/.svn/wc.db"; fi
if [ ! -f "$WCDB" ]; then echo "异常:svn wc.db 不存在,技能终止"; exit 1; fi
ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 \
  ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_krl.txt"
```
- `ReadFileListFromSvnDB=1` → 走 `CopyDataFromWCDBList`:清单(ScanFileListInput)INNER JOIN svn wc.db 取清单文件的元信息(changed_revision/date/author)填 FileList,再 `ProcessMultiThreadMain` 解析——**仍扫清单全量**(不漏文件),只是 FileList 多带 svn 元信息、多~8s 查 svn db。
- `bTest=1` → 测试环境,不上报。
- 工具 `setlocale(LC_ALL, ".936")`,自己处理 GBK,中文路径 OK。
- **krl 调用路径**:见 §1 末尾(reader 工厂 `ProcessKrl` → `KRL::ReadFile`)。依赖路径经 `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

### 5.3 音频标签扫描
**无**。krl 没有音频标签(spec 明确),不跑 `KSearchResource.exe SearchAudioLabel`,不产生 `AudioLabel.db`(同 Ani)。

### 5.4 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下最新时间戳子目录。`ls -t logs/JX3/trunk/ | head -1`。
- `Scan.log`:末尾应类似 `... INFO 日志正常关闭`。
- `ScanResult.db`(**krl 不关注 Pss 表**,看这些):
  - `FileList`:扫到的文件集(应含全部 ~7.7 万 .krl)。
  - `Result`:krl 的依赖路径落库在这——
    - 解析失败:`ErrLevel=7` 且 `File` 以 `.krl` 结尾(罕见,顶层 default 是软失败不挂;失败多是文件损坏/identifier 不符)。
    - 依赖路径:`File` 以 `.krl` 结尾的记录,`SonFile`/`SonExtName` = 抽出的依赖(mesh/mtl/ani/portrait 等),`ErrLevel` 多为 3/5。
    - `ERROR_TYPE_OLDER_KRL`(版本太老):含新版本的 .krl 落 default 报此错,该 .krl 漏抽全部依赖——**这是 krl 落后的主要信号**,diff 里表现为"扫到但依赖集为空/异常"。
  - (无 krl 专门"成功"表——不像 Pss 有 `Pss` 表;同 kmsc/tani。)

---

## 6. 差异对比（闭环的"看变化"）

`diff_krl.py` 是**纯差异工具**(同 kmsc/Ani/tani 方案):只列修改前后数据差异,**不判断差异算回归还是改善**(好坏由报告/Claude 人工裁定)。资源对错是 `KRL.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报的职责,不是 diff 的职责。

每轮:改码前跑一次全量(baseline ScanResult.db),改+编译后再跑一次(current),对比:
```bash
python "$REPO/.claude/skills/krl代码同步/scripts/diff_krl.py" "<baseline ScanResult.db>" "<current ScanResult.db>" --knownbad "<清单,可选>"
```
- **无 `--audiolabel`**(krl 无音频,同 Ani)。
脚本输出(纯差异,中性):
- **changed**:两侧都解析成功(都在 `Result` 但非 `ErrLevel=7`),但依赖集变了(中性,不判好坏)。如修复某版本漏抽导致依赖变化会列在此。
- **appeared**:current 新进(baseline 失败/未扫到)——如修复版本外漏抽(新版本 .krl 从 default 报错变为抽到依赖)。
- **disappeared**:baseline 有、current 不在了(需关注,可能回归)。
- **still_failing**:两侧都失败(`ErrLevel=7` .krl)。与 `--knownbad` 交集 = 预期坏文件(截断/损坏);其余待人工裁定。
- **new_fail**:baseline 没扫到、current 却失败(同清单下一般不出现,出现即异常)。
- **stable**:两侧都成功且依赖集完全相同。
- (diff 比一类:解析失败集 `Result` `ErrLevel=7` .krl + 依赖路径集 `Result` `File=.krl` 的 `SonFile`;**无音频对比**)
- exit code:0=正常(差异已列);1=异常(`new_fail` 非空);2=输入异常。**差异本身不导致 exit1**。

**如何裁定差异**:
- `changed`/`appeared` 里属本轮目标(如同步 V6 后新版本 .krl 抽到依赖)= 预期改善,通过。
- `changed` 里属不该碰的版本(如 V0 依赖莫名变了)= 回归,回滚重来。
- `disappeared`/`new_fail` = 需关注,逐个排查。

**整个闭环终止** = §2 差异比对无待同步项 且 diff 列出的差异全部裁定为"预期"(无意外 `disappeared`/`new_fail`/非目标 `changed`) 且 无 `still_failing` 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经你核实(打开文件看是否截断/损坏,类比 `CodeReviewKMSC` 的 32KB 截断案例)后,记进 `--knownbad`,后续不再当回归。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查(6 项:4 环境变量+MSBuildTool+wc.db),任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成全量 krl 清单(--root $JX3_HD_Client/represent/rl --ext krl)→ 跑扫描器(§5.2)得 baseline ScanResult.db → 存路径
          (krl 无音频,不跑 SearchAudioLabel)
B. 比对:  按 §2 两层(版本层 V0-V5 switch / per‑version 结构层)比对复刻↔引擎,列当轮待同步项
          (重点:switch 缺 V6+(§2.1) + 各版本 KGRL_FILE_*_V* 结构字段/大小/pack(§2.2,遍布各版本);
           先核实新版本是否真序列化进 .krl;区分"字节布局差异"与"运行时逻辑差异")
C. 改码:  改 KRL.cpp/KGRLFormat.h/KRL.h(UTF-8,Edit/Write 安全)同步该版本/结构;
          同步时逐条核 §3 一类信息(依赖路径)是否补齐;每段 Reference(sizeof)要与引擎该版本字节数一致
D. 编译:  §4 先编 RUST 依赖(KESMBase/ClipLib,§4 前置)→ 再 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C(LNK1104查遗留进程或RUST lib没编)
E. 测试:  用 baseline 同一份清单 → 跑扫描器得 current ScanResult.db
          (无音频扫描)
F. 判据:  diff_krl.py baseline vs current
          - 有意外差异(disappeared/new_fail/非目标 changed) → 回滚本轮改动,回到 B
          - 差异全部裁定为预期 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 差异全部预期 → 完成
          写报告 UpdateCodeKrl.md(§9),再汇报
```

> **只有真正改了代码才写报告**(§9)。两层已对齐、没改码(如纯健康基线检查),不写报告、只在对话里说明。

护栏(同 Pss/kmsc/Ani/tani):
- **迭代上限:最多 8 轮**。8 轮仍未清零或反复异常,停止并汇报当前状态(别死循环)。
- **B 编译错优先**:编译不过绝不进测试。
- **C 回滚要干净**:有意外差异时把 `KRL.cpp`/`KGRLFormat.h`/`KRL.h` 恢复到本轮改前状态(改前 `cp` 备份到临时目录最稳)。
- **D 编码**:源码 UTF-8 可 Edit/Write;`ScanFileList_krl.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **E 全量是默认**:~7.7 万文件/轮,实测约十几秒(见 §5),不慢。想对单个新版本先快速试错,可用 `regen_scanlist.py --subset` 缩小清单;但终止判据仍以全量无意外差异为准,子集只用于迭代试错。
- **F 一类信息**:每轮同步后核 §3 一类(依赖路径)是否补齐——这是"假成功"主要来源(krl 无音频、无数值汇总,只这一类;特别注意新版本 .krl 落 default 的 `ERROR_TYPE_OLDER_KRL` 是漏抽信号)。
- **G 不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户，同 Pss/kmsc/Ani/tani）

1. 同步了哪些版本/结构(逐项:引擎文件:行 → 复刻文件:行,补了哪个 `KGRLFileType::V*` case + per‑version `LoadUnitFromBufferV*` + 依赖路径登记)。
2. 编译状态 + 测试范围(全量 ~7.7 万,耗时)。
3. 差异对比:baseline vs current 的 `changed/appeared/disappeared/still_failing/new_fail` 计数;known-bad 清单。
4. 终止结论:差异是否清零、差异是否全部预期;撞上限则说明卡在哪轮/哪个版本。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后(类比 `CodeReviewKMSC` 的截断判断法),给出下一步。

---

## 9. 对比测试报告（落盘 UpdateCodeKrl.md）

按 `CodeReviewKrl.md` §5/§6 要求,真正改了代码后,闭环收尾把报告写到:
`项目路径\x64\Release\logs\UpdateCodeKrl.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(同 Pss 但**不关注 Pss 表**,重点是 `Result`/`FileList`;**无 AudioLabel**,不跑音频扫描,同 Ani):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`;没有 = `Jx3SvnHookCheckTool.exe` 执行失败。
2. **ScanResult.db 逐表对比**:表 `FileList`/`Result` 内容——相同、不同,及不同原因(**不关注 Pss 表**)。

### 9.1 报告生成方式(脚本 + Claude 分工,同 Pss/kmsc/Ani)
```bash
REPO="$(pwd -W)"
python "$REPO/.claude/skills/krl代码同步/scripts/gen_report_krl.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "$REPO/x64/Release/logs/UpdateCodeKrl.md"
```
- 脚本逐表对比 ScanResult(FileList/Result,**不关注 Pss 表**)+ 检查 Scan.log,输出 md 片段(UTF‑8)。
- **无 `--audiolabel`**(krl 无音频,同 Ani)。
- 脚本只给数字和样本,**"代码改动说明"和"不同原因"由 Claude 据本次改动补写**在脚本片段之上。

### 9.2 UpdateCodeKrl.md 结构(参考 Pss/kmsc/Ani 的 UpdateCodePss/UpdateCodeKmsc/UpdateCodeAni.md 范式)
```
# Krl 代码修改前后对比测试报告
> 生成日期 / 对比 baseline vs current / 全量 ~7.7 万 krl

## 一、本次代码改动            ← Claude 写(引擎文件:行 → 复刻文件:行,补了什么)
## 二、前后对比结果             ← gen_report_krl.py 脚本片段(Scan.log + ScanResult[不关注Pss])
## 三、不同原因分析             ← Claude 写(逐表解释为什么不同,与本次改动的因果)
## 四、终止结论                 ← Claude 写(差异清零/无回归/是否撞上限;遗留建议)
```
- "二"由脚本 `>>` 追加;"一/三/四"由 Claude 写在片段上下。
- 报告 UTF-8(用 Write/Edit),**不是 GBK**——中文要正常显示。

**⚠️ "三、不同原因分析"必须详细说明差异来源**(不只列数字):
- 对每个有差异的表/字段,**说清差异从哪来**——是本次代码改动导致的(如"同步 V6 后,X 个新版本 .krl 从 ERROR_TYPE_OLDER_KRL 漏抽变为抽到依赖")、还是数据本身变动、还是工具行为差异。
- 把差异和"一、本次代码改动"对应起来:哪条改动产生了哪条差异、为什么。
- 对 `changed`/`appeared`/`disappeared` 各类,逐类说明来源。
- 若某差异与本次改动**无关**(意外),单独标出并说明可能原因(这才是需回滚/排查的)。

---

## 附:快速命令速查

```bash
# 仓库根:Claude 执行技能时 cwd 本就在仓库根,pwd -W 直接取到。
# ⚠️ 勿在 x64/Release 里用 cd .. && pwd -W 取 REPO(cd .. 只退到 x64 一级→REPO=仓库根/x64,多了一个 x64 段→拼 $REPO/x64/Release/logs/ScanFileList*.txt 成 仓库根/x64/x64/Release/logs/ScanFileList*.txt,x64 重复、文件不存在→MainScan GetLastError(3) 扫0文件);从仓库根 pwd -W 直接取。
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO"

# 生成全量 GBK krl 清单(深扫 represent/rl 下 .krl)
python "$REPO/.claude/skills/krl代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/represent/rl" --ext krl \
  --out   "x64/Release/logs/ScanFileList_krl.txt"

# 编译(先编 RUST 依赖 KESMBase/ClipLib,再编 FileParse.sln;FileParse.sln 不含这两个工程)
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" \
  FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal

# 全量扫描(ReadFileListFromSvnDB=1;清单 JOIN svn db 取元信息,仍扫清单全量;无音频扫描)
cd "x64/Release"
WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"
[ -f "$WCDB" ] || { echo "异常:svn wc.db 两个候选都不存在,技能终止"; exit 1; }  # 上级/本级 .svn 必须存在一个(§1 前置已查,此为兜底)
ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_krl.txt"

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1

# 差异对比(失败集+依赖,纯差异不判好坏,无音频)
python "$REPO/.claude/skills/krl代码同步/scripts/diff_krl.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>"

# 生成对比报告片段(ScanResult[不关注Pss]+Scan.log,无 AudioLabel)
python "$REPO/.claude/skills/krl代码同步/scripts/gen_report_krl.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodeKrl.md"   # Claude 再补"代码改动/不同原因/结论"于其上
```
