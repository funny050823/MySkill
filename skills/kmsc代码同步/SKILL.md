---
name: kmsc代码同步
description: 把 Kmsc 复刻解析器(Kmsc::ReadFile)与引擎原函数(KPlotLoader::LoadPlotData)对齐,修复"复刻落后引擎"导致的 .kmsc(协议动画)解析失败/漏抽依赖路径/漏抽音频标签。当用户提到 kmsc 解析失败、协议动画解析失败、Kmsc 复刻落后引擎、KMovieObject/KPlotLoader 对齐、NewAction/NewObject 新类型未同步、kmsc 漏抽依赖路径或音频、或想让 KResourceReader 正确解析新类型 .kmsc 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到差异清零且无意外差异为止。
---

# KMSC 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `Kmsc::ReadFile` 是引擎 `KPlotLoader::LoadPlotData` 的**复刻**,解析 `.kmsc` 协议动画文件。复刻只"读得动 + 抽资源检查需要的依赖路径/音频标签",不跑动画。引擎会持续新增/修改对象类型(`EnumObjectType`/`MOT_*`)、动作类型(`EnumActionType`/`EAT_*`)、结构体。复刻一旦没跟上,遇到新类型的 `.kmsc` 就会**解析失败**或**漏抽依赖**。

⚠️ **KMSC 比 PSS 更怕落后**:复刻 `Kmsc::NewAction` 的 `switch` 有 80+ case,但 `default` 是 `KG_PROCESS_ERROR(FALSE)` **硬失败**——引擎只要新增一个动作类型,复刻遇到含该动作的 kmsc 就直接解析挂掉(Pss 是错位、可能静默;kmsc 是硬挂)。这是 kmsc 最核心的落后风险点。`NewObject` 的 `default` 仅打印不致命,但缺 case 会导致 `m_pKMovieObject` 为 NULL、后续 `LoadFileHeader` 失败 → 该 kmsc 失败。

本技能把"对齐复刻与引擎"做成**全自动闭环**(同 Pss):比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 有意外差异就回滚,直到差异清零。过程中**守住两类信息抽取口径**(kmsc 没有数值汇总,只有路径+音频两类)。

> 工作模式:**全自动闭环**(同 Pss),中途不必征询用户,收尾汇报。护栏见 §7。仅在 windows 下执行。

---

## 1. 锁定路径（别取错）

> **前置环境检查(同 Pss,进技能第一步先做,缺了直接报错、不继续)**:本技能依赖一组 Windows 环境变量(系统配置,非会话临时设),编译/对标都要用。进 §7 闭环 A 步前,先逐个核实存在:
> | 环境变量 | 必需 | 用途 | 缺失后果 |
> |---|---|---|---|
> | `JX3ENGINE_Sword3` | **必** | 引擎源码根(`...\Source\KG3DEngineDX11\...`),对标口径 + 编译 include/lib | 找不到引擎文件、编译失败 |
> | `JX3ENGINE_BASE` | **必** | 编译 include/lib(`$(JX3ENGINE_BASE)\include` 等) | 编译失败 |
> | `JX3ENGINE_DevEnv` | **必** | 部分工程编译用(`$(JX3ENGINE_DevEnv)/Include` 等) | 编译失败 |
> | `JX3_HD_Client` | **必** | client 测试数据根(全量扫描输入),指向 `...\sword3-products\trunk\client`,内容以 GB 计、不会为空 | 全量扫描无数据 |
> | `MSBuildTool` | **必** | MSBuild.exe 路径(编译 `FileParse.sln`),指向 `...\2019\...\Bin\MSBuild.exe` | 编译失败 |
> | svn `wc.db` | **必** | `$JX3_HD_Client/../.svn/wc.db` 或 `$JX3_HD_Client/.svn/wc.db` 之一(exe 要求 `PathFileExistsA(pszDBFile)` 真) | 扫描器报"参数错误" |
> - 检查命令(bash,同 Pss):`for v in JX3ENGINE_Sword3 JX3ENGINE_BASE JX3ENGINE_DevEnv JX3_HD_Client; do [ -d "${!v}" ] && echo "$v OK=${!v}" || echo "$v 缺失/无效,技能终止"; done; [ -f "$MSBuildTool" ] && echo "MSBuildTool OK=$MSBuildTool" || echo "MSBuildTool 缺失/无效,技能终止"; WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"; [ -f "$WCDB" ] && echo "wc.db OK=$WCDB" || echo "wc.db 异常,技能终止"`
> - 任一**必需**项缺失 → 报错并停止。

> **项目路径(仓库根)**(同 Pss):`KResourceReader` 仓库根 = 本 SKILL.md 上溯 4 级 = Claude 执行技能时的工作目录(Primary working directory)。说明路径写作 `项目路径\...`;bash 命令块用 `REPO="$(pwd -W)"`(Windows 绝对,exe 能接受),块内 `$REPO/...`;传 exe 的文件路径必须绝对(exe 内部 `SetCurrentDirectoryA` 到 client,相对路径失效)。Claude 执行技能 cwd 本就在仓库根,`pwd -W` 直接对。

复刻侧（你要改的，UTF‑8，Edit/Write 安全）:
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`Kmsc.cpp`/`KMovieObject.cpp` 编进此工程,以 `..\src\Kmsc\Kmsc.cpp` 等引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\Kmsc\Kmsc.cpp`（顶层 `ReadFile`/`NewObject`/`NewAction`）
- `项目路径\src\Kmsc\KmscHeader.h`（`FileHeader`/`KTrans` 等结构,且 `#include` 枚举头 `IKMovieTypeDef.h`）
- `项目路径\src\Kmsc\Kmsc.h`
- `项目路径\src\Kmsc\KMovieObject.cpp` + `.h`（各对象/动作 `LoadFromFile`,~192KB,**抽取依赖路径/音频都在这**）
  - 若上面不存在,从本 SKILL.md 目录上溯 4 级再下 `src\Kmsc`:`%cd%\..\..\..\..\src\Kmsc\Kmsc.cpp`(`%cd%` 指本 SKILL.md 目录,非 CodeReviewKMSC.md 目录)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG_Movie\KG_MovieCore\KG_MovieCore_2019.vcxproj`(`KPlotLoader.cpp` 在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG_Movie\KG_MovieCore\KPlotLoader.cpp` 的 `KPlotLoader::LoadPlotData`（+ `ReadObjectDataFromFile`/`ReadActionDataFromFile`/`ReadObjRelativeFromFile`/`NewObject`/`NewAction`）
- **per‑type 对象/动作读取(逐类型同步的真正落点)**:`...\KG_Movie\KG_MovieCore\Object\*.cpp`,各 `KMovieActor/KMovieCamera/KMovieDirector/KMoviePlayer/KMovieReferenceObject/KMovieLight/KMovieRectLight/KMovieVDBObject/KMovieMaterialVolume/KMovieWwiseObject...::LoadFromFile`/`LoadFromFileEx`,及各 `KMovieAction*::LoadFromFile`。
- **读写基准**:`...\KG_MovieCore\KMovieScene.cpp` 的 `SaveToFile`/`WriteObjDataToFile`/`WriteActionDataToFile`/`SaveFileHeader`(writer 与 reader 字节数逐一吻合的基准)。
- **枚举(口径来源)**:`EnumObjectType`(`MOT_*`)/`EnumActionType`(`EAT_*`)在 `IKMovieTypeDef.h`。复刻 `KmscHeader.h` `#include` 此头(**枚举 include 不自维护**,与 Pss 自复制不同),靠 vcxproj `AdditionalIncludeDirectories=$(JX3ENGINE_Sword3)\...` 解析到引擎头——故 kmsc 枚举值通常与引擎自动同步,落后风险**不在枚举值、在 `NewObject`/`NewAction` 的 switch case**。

对标源总览:
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层遍历 | `KPlotLoader::LoadPlotData` | `Kmsc::ReadFile` |
| 对象数据 | `ReadObjectDataFromFile` + `NewObject` | `Kmsc::ReadObjectDataFromFile` + `NewObject` |
| 动作数据 | `ReadActionDataFromFile` + `NewAction` | `Kmsc::ReadActionDataFromFile` + `NewAction` |
| 对象相对 | `ReadObjRelativeFromFile` | `Kmsc::ReadObjRelativeFromFile` |
| per‑type 对象 | `Object/*.cpp` 各 `KMovieXxx::LoadFromFile/LoadFromFileEx` | `KMovieObject.cpp` 各 `kg_read_obj::KMovieXxx::LoadFromFile/LoadFromFileEx` |
| 动作 per‑type | `KMovieAction*::LoadFromFile` | `KMovieObject.cpp` 各 `kg_read_action::KMovieActionXxx::LoadFromFile` |
| 枚举 | `IKMovieTypeDef.h`(`EnumObjectType`/`EnumActionType`) | `KmscHeader.h` include 同一头 |
| 读写基准 | `KMovieScene.cpp` `SaveToFile` 系列 | (复刻只读不写,用 writer 反推 reader 字节数) |

---

## 2. 差异比对法（每轮第一步）

引擎 `LoadPlotData` 顺序读:FileHeader → FrameRate → 版本分支路径(>=7 FocusActor、>=6/5/4/3 各 MAX_PATH)→ 对象段(`nSaveObjectNum` × [dwType+KTrans+对象])→ 动作段(`nActionNum` × [前置index+type+elementID+动作])→ 相对段(version>=2)。复刻 `ReadFile` 已与之一一对齐(顶层版本分支已核验)。

⚠️ **差异重点有两个,缺一不可**:
1. **per‑type 的对象/动作 switch 是否缺 case**(§2.2/§2.3)——新增类型。
2. **版本分支层**(§2.5)——**遍布解析全程,是更普遍的落后来源**:代码里有大量版本标识数字(顶层 `dwVersion`、各对象/动作自己的 `pdwVersion`、`dwMask`),**新版本号恒大于老版本号,引擎新版本会在 `>= N` 分支里加新字段/新读取**。复刻没跟到新版本号就错位/漏抽。这不只 NewAction 一种,而是**每个对象/动作的 LoadFromFile 内部都有版本分支**,需系统比对。

### 2.1 枚举层(先确认来源)
- 确认 `KmscHeader.h` 的 `#include "..\..\JX3Interface\Include\KG3DMovie\IKMovieTypeDef.h"` 实际解析到引擎头(编译能过即解析得到)。若解析到引擎头 → `EnumObjectType`/`EnumActionType` 枚举值与引擎自动同步,**枚举层无落后风险**。
- 仍要做的:对比引擎 `IKMovieTypeDef.h` 的 `MOT_*`/`EAT_*` 全集 vs 复刻 `NewObject`/`NewAction` switch 的 case 集——**缺 case 才是真落后**。

### 2.2 对象类型层(`NewObject` switch,`MOT_*`)
- 引擎 `KPlotLoader::NewObject` switch 的 `MOT_*` case 集。
- 复刻 `Kmsc::NewObject` switch 的 case 集(约 25 个,含 `MOT_FLEXEFFECT_FLUID/RAG` 注释掉只报错、`MOT_FOCUS_SETTER` 空实现)。
- 差集:引擎有、复刻缺的 `MOT_*` = 候选同步项。复刻 `default` 仅 `KG_PRINT_ERROR`(不致命),但缺 case → `m_pKMovieObject` 保持 NULL → 后续 `LoadFileHeader` 失败 → 该 kmsc 失败。
- 逐类型核实是否真被序列化进 `.kmsc`(编辑器‑only 类型如 `MOT_FLEXEFFECT_*`、`MOT_FOCUS_SETTER` 注释说明"只编辑器用",不必同步)。

### 2.3 动作类型层(`NewAction` switch,`EAT_*`)— **重点**
- 引擎 `EnumActionType` 全集(从 `IKMovieTypeDef.h` 取所有 `EAT_*`,注意 `EAT_IllEgalActionType=-1` 是哨兵)。
- 复刻 `Kmsc::NewAction` switch 的 case 集(80+ 个,含 `EAT_FKBoneAni`/`EAT_IKBoneAni` 落到 `KG_PROCESS_ERROR(FALSE)`)。
- 差集:引擎有、复刻缺的 `EAT_*` = **候选同步项**。⚠️ 复刻 `NewAction` 的 `default` 是 `KG_PROCESS_ERROR(FALSE)` **硬失败**——引擎新增任何动作类型,含该动作的 kmsc **直接解析失败**。这是 kmsc 落后最严重的表现,也是闭环要消灭的主要目标。
- 逐类型核实是否真被序列化(`EAT_FKBoneAni`/`EAT_IKBoneAni` 引擎侧也 `_ASSERTE(0)`,不序列化,不必同步)。
- 对每个确认要同步的动作:去引擎找对应 `KMovieActionXxx::LoadFromFile`,**按字节顺序**把读取序列搬进复刻 `KMovieObject.cpp` 的 `kg_read_action::KMovieActionXxx::LoadFromFile`,套用复刻现有动作风格。

> **关于 `NewAction` 超范围/缺 case 的 `default` 行为(无需改)**:复刻 `default` 是 `KG_PROCESS_ERROR(FALSE)` **硬失败**(在 `NewAction` 内部直接失败);引擎 `KActionFactory::CreateMovieAction` 对未知类型**返回 null**,由调用方 `KG_PROCESS_ERROR(pMovieAction)` 失败(`KMovieActionGroup.cpp:109/324`、`KPlotLoader::ReadActionDataFromFile`)。两者最终结果一致——含未知动作类型的 kmsc **都解析失败**,只是复刻失败点早一步(在 NewAction 内)、引擎晚一步(在调用方)。资源检查角度行为一致,**复刻处理合理,无需改成"返回 null"**。这个硬失败反而是好事:引擎将来新增动作类型时,含它的 kmsc 会**立即解析失败暴露**(而非静默漏抽),闭环到时按本节补 case 即可。

### 2.4 结构体层
- 引擎 `KMovieScene::FileHeader`、`KTrans`(vTrans+vScaling+vRotation = 12+12+16=40)、各对象/动作 `FileHeader` 与 body 结构。
- 复刻 `KmscHeader.h` 的对应结构。
- 差异:引擎结构新增字段/改大小(常带版本分支 `dwVersion >= N` 加读取)→ 复刻结构体与版本分支都要同步,**否则后续字段错位**。用 `KMovieScene.cpp` 的 `SaveToFile` 系列反推 writer 字节数,与复刻 reader 逐一核对。

### 2.5 版本分支层(遍布全程,重点) — **普遍的落后来源**
解析全程有大量版本标识数字,**新版本号恒大于老版本号,引擎新版本在 `>= N` / `> N` 分支里加新字段/新读取**,复刻没跟就错位/漏抽。比 case 缺失更普遍——不只 NewAction,每个对象/动作的 `LoadFromFile` 内部都有:
- **顶层 `dwVersion`**:`Kmsc.cpp` 顶层 `if (dwVersion >= 7/6/5/4/3/2)` 一串(每升一版加一段)。复刻特判 `>=8 报错"工具只支持到7"`——说明工具认到 7,引擎若已到 8+ 则需补 `>=8` 分支。
- **per‑type `pdwVersion`**:`KMovieObject.cpp` 各对象/动作自己的版本号,如 `KMovieActor::LoadFromFileEx` 内 `if (*pdwVersion > 0x01/>0x02/>0x03/>=0x05/>=0x06/>=0x07/>=0x08)` 一堆分支——每个类型独立版本,新版本加字段。引擎某类型从 0x07 升 0x08 加了字段,复刻没跟则该类型解析错位。
- **`dwMask`** (ani 亦同模式):文件格式版本。
- **比对法**:对每个 per‑type `LoadFromFile`,逐个核两侧的版本分支上限是否一致(引擎最高 `>= N`、复刻最高 `>= M`,若 `N > M` 则复刻缺新版本分支 → 同步:补 `>= M+1...N` 分支 + 对应新字段读取,对齐引擎 `SaveToFile` 该版本写入的字节)。grep `dwVersion|pdwVersion|>= 0x|> 0x` 各取两侧分支上限做对比。

> 实操:grep 各取两侧 `MOT_*`/`EAT_*` 做 case 集合差(§2.2/§2.3),grep `dwVersion|pdwVersion|>= 0x|> 0x` 比版本分支上限(§2.5),再人工逐项按 2.2/2.3/2.4/2.5 核实。结论写进当轮记录(改了哪个类型/补了哪个版本分支/对应引擎文件:行)。

---

## 3. 两类信息抽取（同步时的不变量，必须守）

⚠️ **kmsc 没有 PssInfo 那样的数值汇总**(无包围盒/粒子数/材质数等),它只抽**两类**:明文依赖路径 + 音频标签。同步任何新对象/动作类型时,这两类**必须跟着补**。**口径以宏为信号,宁多勿漏**:凡是见到 `MAX_PATH`/`FILENAME_MAX` 参与 `Reference(..., sizeof(char)*MAX_PATH)` 读取,就可能是外部资源路径,一律登记,不靠字段名过滤。

### 3.1 明文依赖路径（`OnReadResourceFileByGBK(路径, ...)`）
登记接口 `OnReadResourceFileByGBK`(经 `Kmsc::OnReadResourceFileByGBK` 包装,带 `IsSkip` 过滤绝对路径)。已知登记点(`Kmsc.cpp`/`KMovieObject.cpp` 行号会随代码变):
| 来源 | 位置 | 备注 |
|---|---|---|
| 顶层 `Kmsc::ReadFile` | version>=6/5/4/3 的 4 条 MAX_PATH 路径 | PlayerSpotLightEnv/PlayerEnvSetting/RCidx/EnvSetting/PostSetting |
| `KMovieObject.cpp` 各对象/动作 | ~25 处 `OnReadResourceFileByGBK` | mesh/mtl/ani/jsoninspack/mdl/tani/ini/sfx/ogg 等 |

实测依赖类型分布:jsoninspack(最多) > mtl > ani > mesh > inspack > mdl/tani/ini/sfx/ogg。同步新类型时对照分布,看该抽的路径抽没抽到。

### 3.2 音频标签（`KGShare::SoundLabel::Instance().AddWwiseEvent` / `AddFmod`）
凡是涉及音效标签的一律捞,不得漏。新增带音频的对象/动作必须补登记。
| 来源 | 调用 | 大致行号 | 类型 |
|---|---|---|---|
| `KMovieActionMusic::LoadVersion0` | `AddFmod(GetSrcFile(), pszFile)` | `KMovieObject.cpp:3167` | fmod 事件 + .ogg/.wav/.mp3 依赖 |
| `KMovieActionWwiseEvent::LoadFromFile` | `AddWwiseEvent(GetSrcFile(), pszFile)` | `KMovieObject.cpp:4493` | Wwise EventName |

> 每轮同步后,逐类型自问:这个新对象/动作的 `MAX_PATH` 读取登记依赖了吗?有音频吗(AddWwiseEvent/AddFmod)?两类都要有结论。**没有第三类(数值汇总)**——别照搬 Pss 的 §3.3。

---

## 4. 构建（同 Pss）

编译整个解决方案产出扫描器(`Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- `Kmsc.cpp`/`KMovieObject.cpp` 在 `Jx3ResFileReaderAPI.vcxproj`。
- MSBuild:用 `%MSBuildTool%`(见 §1)。命令(在仓库根,用相对 `FileParse.sln`):
  ```bash
  "$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
  ```
  - bash 下 MSBuild 的 `/` 参数写成 `//`。
- **不要用 `Build.cmd`**(带 svn up/git 推送/PE 核验副作用)。
- 判定:退出码 0 且 `x64\Release\Jx3SvnHookCheckTool.exe` 更新时间刷新即成功。编译失败 → 看 MSBuild stdout 先修编译错。
- ⚠️ 编译遇 LNK1104 打不开 dll/exe → 多半有遗留 `Jx3*` 工具进程锁着,`tasklist | grep Jx3` 查、`taskkill //PID //F` 结束后重试。

---

## 5. 测试（全量）

全量 = 扫 `$JX3_HD_Client\data\movie\` 下所有 `.kmsc`(本机约 **1039** 个,实测数秒)。

### 5.1 生成扫描清单(GBK!)
`ScanFileList_kmsc.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 写**(UTF‑8 破坏中文)。用脚本:
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
python ".claude/skills/kmsc代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/movie" --ext kmsc \
  --out   "$REPO/x64/Release/logs/ScanFileList_kmsc.txt"
```
(kmsc 用独立清单 `ScanFileList_kmsc.txt`,避免与 Pss/Ani 的清单互相覆盖。)

### 5.2 跑扫描器(关键:ReadFileListFromSvnDB=0)
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO/x64/Release"
# svn wc.db:client 上级是副本根→../.svn,自身是副本根→.svn,两者必须存在一个(§1 前置已查,此为兜底)
WCDB="$JX3_HD_Client/../.svn/wc.db"
if [ ! -f "$WCDB" ]; then WCDB="$JX3_HD_Client/.svn/wc.db"; fi
if [ ! -f "$WCDB" ]; then echo "异常:svn wc.db 不存在,技能终止"; exit 1; fi
ReadFileListFromSvnDB=0 bTest=1 ForDebug=0 \
  ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_kmsc.txt"
```
- `ReadFileListFromSvnDB=0` → 走 `ScanByFileList` 精确扫清单(=1 查 svn db 改动文件,非全量)。
- **kmsc 调用路径**:`Jx3SvnHookCheckTool.exe` → `Jx3ResFileReaderAPI`(reader 工厂按扩展名分派)→ `ProcessKmsc` → `new kg_kmsc::Kmsc`(`Jx3ResFileReaderAPI.cpp:268`)→ `Kmsc::ReadFile`。

### 5.3 跑音频标签扫描(改码前后各一次,路径不同!)
音频标签(§3.2 的 AddWwiseEvent/AddFmod)不落 `ScanResult.db`,落独立的 `AudioLabel.db`,由 `KSearchResource.exe SearchAudioLabel` 全库扫产出。kmsc 的音频标签在 `File` 表 `.kmsc` 部分(本机约 1400 行)。
```bash
REPO="$(pwd -W)"
cd "$REPO/x64/Release"
# 改码前(baseline):前后必须不同 db 文件名!InitDB 会先删同名 db
ForDebug=0 ./KSearchResource.exe SearchAudioLabel "$JX3_HD_Client" "$REPO/x64/Release/logs/AudioLabel_kmsc_baseline.db"
# 改码后(current):换文件名
ForDebug=0 ./KSearchResource.exe SearchAudioLabel "$JX3_HD_Client" "$REPO/x64/Release/logs/AudioLabel_kmsc_current.db"
```
- `argc==4`:`argv[1]=SearchAudioLabel`,`argv[2]=client`,`argv[3]=output db`。
- ⚠️ **前后必须不同 db 文件名**。`SoundLabel::InitDB` 先 `DeleteFileA` 再建,同路径后跑必覆盖先跑。
- ⚠️ **跑完保留 AudioLabel_kmsc_*.db,不要删**。这是技能输出文件,留在 `x64\Release\logs\` 供查阅/复算,**禁止 rm 删除**(清理临时只清 ScanFileList 等纯中间产物,AudioLabel db 不算中间产物)。
- `SearchAudioLabel` 是全库扫(含 pss/tani),kmsc 技能只取 `File` 表 `.kmsc` 部分。

### 5.4 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下最新时间戳子目录。`ls -t logs/JX3/trunk/ | head -1`。
- `Scan.log`:末尾应类似 `... INFO 日志正常关闭`。
- `ScanResult.db`(**kmsc 不关注 Pss 表**,看这些):
  - `FileList`:扫到的文件集(应含全部 1039 个 .kmsc)。
  - `Result`:kmsc 的两类落库都在这——
    - 解析失败:`ErrLevel=7` 且 `File` 以 `.kmsc` 结尾。
    - 依赖路径:`File` 以 `.kmsc` 结尾的记录,`SonFile`/`SonExtName` = 抽出的依赖,`ErrLevel` 多为 3/5。依赖类型见 §3.1 分布。
  - (无 kmsc 专门"成功"表——不像 Pss 有 `Pss` 表。)

---

## 6. 差异对比（闭环的"看变化"）

`diff_kmsc.py` 是**纯差异工具**(同 Ani 技能方案 a):只列修改前后数据差异,**不判断差异算回归还是改善**(好坏由报告/Claude 人工裁定)。资源对错是 `Kmsc.cpp`/`KMovieObject.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报的职责,不是 diff 的职责。

每轮:改码前跑一次全量(baseline ScanResult.db + baseline AudioLabel.db),改+编译后再跑一次(current),对比:
```bash
python ".claude/skills/kmsc代码同步/scripts/diff_kmsc.py" "<baseline ScanResult.db>" "<current ScanResult.db>" \
  --audiolabel "<baseline AudioLabel.db>" "<current AudioLabel.db>" --knownbad "<清单,可选>"
```
脚本输出(纯差异,中性):
- **changed**:两侧都在某数据集但值变了(中性,不判好坏)。如修复 NewAction 漏抽导致的依赖/失败变化会列在此。
- **appeared**:current 新进(如修复漏抽)。
- **disappeared**:baseline 有、current 不在了(需关注,可能回归)。
- **still_failing**:两侧都失败。与 `--knownbad` 交集 = 预期坏文件;其余待人工裁定。
- **new_fail**:baseline 没扫到、current 却失败(异常)。
- (diff 比两类:解析失败集 Result ErrLevel=7 .kmsc + 依赖路径集 Result File=.kmsc 的 SonFile;`--audiolabel` 比音频标签 AudioLabel.db File 表 .kmsc 部分)
- exit code:0=正常(差异已列);1=异常(`new_fail` 非空);2=输入异常。**差异本身不导致 exit1**。

**如何裁定差异**:
- `changed`/`appeared` 里属本轮目标(如修复某动作类型)= 预期改善,通过。
- `changed` 里属不该碰的类型 = 回归,回滚重来。
- `disappeared`/`new_fail` = 需关注,逐个排查。

**整个闭环终止** = §2 差异比对无待同步项 且 diff 列出的差异全部裁定为"预期"(无意外 disappeared/new_fail/非目标 changed) 且 无 still_failing 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经核实(打开文件看是否截断/损坏)后记进 `--knownbad`。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查(6 项),任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成全量 kmsc 清单 → 跑扫描器(§5.2)得 baseline ScanResult.db
          + 跑 SearchAudioLabel(§5.3)得 baseline AudioLabel.db → 存两者路径
B. 比对:  按 §2 五层(枚举/对象类型/动作类型/结构/版本分支)比对复刻↔引擎,列当轮待同步项
          (重点:NewAction switch 缺 case(§2.3) + 版本分支上限(§2.5,遍布全程);先核实是否真序列化进 .kmsc)
C. 改码:  改 Kmsc.cpp/KMovieObject.cpp/KmscHeader.h(UTF-8,Edit/Write 安全);
          同步时逐条核 §3 两类信息(路径/音频)是否补齐
D. 编译:  §4 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C(LNK1104查遗留进程)
E. 测试:  用 baseline 同一份清单 → 跑扫描器得 current ScanResult.db
          + 跑 SearchAudioLabel 得 current AudioLabel.db(不同文件名!)
F. 判据:  diff_kmsc.py baseline vs current --audiolabel baseline_audio current_audio
          - 有意外差异(disappeared/new_fail/非目标 changed) → 回滚本轮改动,回到 B
          - 差异全部裁定为预期 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 差异全部预期 → 完成
          写报告 UpdateCodeKmsc.md(§8),再汇报
```

> **只有真正改了代码才写报告**(§8)。四层已对齐、没改码(如纯健康基线检查),不写报告。

护栏(同 Pss):
- **迭代上限:最多 8 轮**。8 轮仍未清零或反复异常,停止并汇报。
- **编译错优先**:编译不过绝不进测试。
- **回滚要干净**:有意外差异时把 `Kmsc.cpp`/`KMovieObject.cpp` 等恢复到本轮改前状态(改前 `cp` 备份到临时目录最稳)。
- **编码**:源码 UTF-8 可 Edit/Write;`ScanFileList_kmsc.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **两类信息**:每轮同步后核 §3 两类(路径/音频)是否补齐——这是"假成功"主要来源(kmsc 无数值汇总,别找第三类)。
- **不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户，同 Pss）

1. 同步了哪些类型/结构(逐项:引擎文件:行 → 复刻文件:行,补了哪个 `MOT_*`/`EAT_*` case + per‑type 读取 + 两类信息登记)。
2. 编译状态 + 测试范围(全量 1039,耗时)。
3. 差异对比:baseline vs current 的 `changed/appeared/disappeared/still_failing` 计数;known-bad 清单。
4. 终止结论:差异是否清零、差异是否全部预期;撞上限则说明卡在哪轮/哪个类型。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后。

---

## 9. 对比测试报告（落盘 UpdateCodeKmsc.md）

按 `CodeReviewKMSC.md` §6 要求,真正改了代码后,闭环收尾把报告写到:
`项目路径\x64\Release\logs\UpdateCodeKmsc.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(文档要求,重点是 `Result`/`FileList`,**不关注 Pss 表**):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`。
2. **ScanResult.db 逐表对比**:`FileList`/`Result` 等内容——相同、不同,及不同原因(**不关注 Pss 表**)。
3. **AudioLabel.db 逐表对比**:`File`/`FilterKmsc`/`LogInfo`/`MovieKrlTxt`/`NewMovieInfo` 内容——相同、不同,及不同原因。

### 9.1 报告生成方式(脚本 + Claude 分工,同 Pss/Ani)
```bash
REPO="$(pwd -W)"
python ".claude/skills/kmsc代码同步/scripts/gen_report_kmsc.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-audio "<baseline AudioLabel.db>" --current-audio "<current AudioLabel.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "$REPO/x64/Release/logs/UpdateCodeKmsc.md"
```
- 脚本逐表对比 ScanResult(FileList/Result,不关注 Pss)+ AudioLabel(File/FilterKmsc/LogInfo/MovieKrlTxt/NewMovieInfo)+ 检查 Scan.log,输出 md 片段(UTF‑8)。
- 脚本只给数字和样本,**"代码改动说明"和"不同原因"由 Claude 据本次改动补写**在脚本片段之上。

### 9.2 UpdateCodeKmsc.md 结构(参考 Pss/Ani 范式)
```
# Kmsc 代码修改前后对比测试报告
> 生成日期 / 对比 baseline vs current / 全量 1039 kmsc

## 一、本次代码改动            ← Claude 写
## 二、前后对比结果             ← gen_report_kmsc.py 脚本片段(Scan.log + ScanResult + AudioLabel)
## 三、不同原因分析             ← Claude 写(重点:详细说明每个差异的来源)
## 四、终止结论                 ← Claude 写
```
- 报告 UTF‑8(用 Write/Edit),**不是 GBK**。

**⚠️ "三、不同原因分析"必须详细说明差异来源**(不只列数字):
- 对每个有差异的表/字段,**说清差异从哪来**——是本次代码改动导致的(如"修复 NewAction 漏抽,使 X 个 kmsc 的依赖从 0 变 N")、还是数据本身变动(如 svn 新增了 kmsc)、还是工具行为差异。
- 把差异和"一、本次代码改动"对应起来:哪条改动产生了哪条差异、为什么。
- 对 `changed`/`appeared`/`disappeared` 各类,逐类说明来源(如"`appeared` 的 N 个 kmsc = 修复了 EAT_Xxx 漏抽后,这些含该动作的 kmsc 从解析失败变成功")。
- 若某差异与本次改动**无关**(意外),单独标出并说明可能原因(这才是需回滚/排查的)。
- 即:**报告要让读者看懂"为什么会有这些差异",而不只是"有 N 条差异"**。脚本只给数字和样本,来源说明靠 Claude 据本次改动 + 回归分析补写。

---

## 附:快速命令速查

```bash
# 仓库根:Claude 执行技能时 cwd 本就在仓库根,pwd -W 直接取到。
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO"

# 生成全量 GBK kmsc 清单
python ".claude/skills/kmsc代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/movie" --ext kmsc \
  --out   "x64/Release/logs/ScanFileList_kmsc.txt"

# 编译
"$MSBuildTool" \
  FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal

# 全量扫描(ReadFileListFromSvnDB=0 走 ScanByFileList)
cd "x64/Release"
WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"
[ -f "$WCDB" ] || { echo "异常:svn wc.db 两个候选都不存在,技能终止"; exit 1; }
ReadFileListFromSvnDB=0 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_kmsc.txt"

# 音频标签扫描(前后用不同 db 文件名)
cd "x64/Release"
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "x64/Release/logs/AudioLabel_kmsc_baseline.db"   # current 轮换 _current.db

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1

# 差异对比(失败集+依赖+音频,纯差异不判好坏)
python ".claude/skills/kmsc代码同步/scripts/diff_kmsc.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>" \
  --audiolabel "<baseline AudioLabel.db>" "<current AudioLabel.db>"

# 生成对比报告片段(ScanResult[不关注Pss]+AudioLabel+Scan.log)
python ".claude/skills/kmsc代码同步/scripts/gen_report_kmsc.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-audio "<baseline AudioLabel.db>" --current-audio "<current AudioLabel.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodeKmsc.md"
```
