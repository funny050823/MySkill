---
name: State代码同步
description: 把 State 复刻解析器(State::ReadFile)与引擎原函数(KG3D_LoadStateFileData)对齐,修复"复刻落后引擎"导致的 .state(状态机)解析失败/漏抽依赖路径。当用户提到 state 解析失败、状态机解析失败、State 复刻落后引擎、KG3D_LoadStateFileData/KState_Load 对齐、state 版本分支未同步、state 漏抽依赖路径(model/ani/socket mesh/mtl/ani)、或想让 KResourceReader 正确解析新版本 .state 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到差异清零且无意外差异为止。
---

# State 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `State::ReadFile`(`kg_state::State`)是引擎 `KG3D_LoadStateFileData` 的**复刻**,解析 `.state` 状态机文件。`.state` 描述一个状态机的若干 state(状态),每个 state 带模型/动画文件 + 可选 socket(插槽的 mesh/mtl/ani);文件还含 behavior/condition/relation 段,但**复刻只抽 state 段里的依赖路径**,不读其他段。复刻只"读得动 + 抽资源检查需要的依赖路径",不跑状态机逻辑。

引擎 `KG3D_LoadStateFileData` 顺序读 6 段:`_LoadState` → `_LoadBehavior` → `_LoadCondition` → `_LoadStateRelations` → `_LoadBehaviorRelations` → `_LoadConditionRelations`;**复刻只读 `_LoadStates`(state 段),注释掉了 `_LoadBehaviors`/`_LoadConditions`**——因为 behavior/condition 段**不含路径**(只读 nType/nID/version/数值,`UNREFERENCED_PARAMETER(pStringData)`),复刻不读它们**不漏抽依赖**(这是 State 技能最关键的特殊点,见 §2.3)。

引擎用**每 state 的 `dwVersion` 字段**做版本分派(`KState_Load` 内 `if(dwVersion>=0x01/0x02/0x03/0x04)`),每升一版加字段/socket 内字段。复刻一旦没跟上引擎新增的 `0x05+`,或 state 段结构没同步,遇到新版本的 `.state` 就会**漏抽依赖**(state 段字段错位 → model/ani/socket 路径读错位)。State 落后多表现为"漏抽/错位",少表现为"解析失败"(文件头不校验 version,无硬失败)。

⚠️ **与 Pss 的关键差异(决定技能不同)**:
1. **只抽一类:明文依赖路径**(state 的 model/ani + socket 的 mesh/mtl/ani),经 `OnReadResourceFileByGBK` 登记。**没有音频标签**(不跑 `KSearchResource.exe SearchAudioLabel`,无 AudioLabel.db)、**没有数值汇总**(无 PssInfo 那样的汇总结构,别找第三类)。同 krl/SRScene/Ani 的"无音频"形态。路径经字符串表(`ReadString` 从 `m_pString` 按 index 取)再登记。
2. **调用路径同 kmsc/krl/SRScene**(reader 工厂):`AddFileType("state", &ProcessState)`(`Jx3ResFileReaderAPI.cpp:159`)→ `ProcessState` → `new kg_state::State` → `State::ReadFile`。注册名小写 `state`,磁盘扩展名也是**小写 `.state`**(本机 668 个,与 SRScene 的大写 `.SRScene` 不同)。
3. **结构自维护**:`State.h` **自维护** `FileHeader`(dwMask+dwVersion+dwExtend[128],pack(1)),非 include 引擎头(同 Ani/krl/SRScene)。落后风险在**文件头 dwExtend 布局/state 版本分支/读取序列**,不在 include 同步。⚠️ 引擎头(`KG3D_StateFile.h` 等)经 include 路径解析,本机未必能直接 Read 到;比对以引擎 `KG3D_StateFile.cpp` 的 `_ReadBuffer(...)`/字段访问反推字节数,与复刻 `State.cpp` 逐一核对。
4. **顶层无版本校验/无硬失败**:复刻 `ReadFile` 读 `FileHeader` 后不校验 `dwVersion`(注释掉了 `dwVersion>=1` 校验),直接从 `dwExtend[0-4]` 取 state/behavior/condition 数 + stringStart。落后不挂整个文件,只漏抽该 state 的路径。

本技能把"对齐复刻与引擎"做成**全自动闭环**(同 Pss/kmsc/Ani/tani/krl/SRScene):比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 有意外差异就回滚,直到差异清零。过程中**守住一类信息抽取口径**(明文依赖路径)。

> 工作模式:**全自动闭环**(同 Pss/.../SRScene),中途不必征询用户,收尾汇报。护栏见 §7。仅在 windows 下执行。

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
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`State.cpp` 编进此工程,以 `..\src\State\State.cpp` 引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\State\State.cpp`(`ReadFile` + `KState_Load`(state 读取,版本分支+抽取)+ `_LoadStates`/`_LoadBehaviors`/`_LoadConditions`(**后两者注释掉,有意不读**))
- `项目路径\src\State\State.h`(`State` 类 + **自维护** `FileHeader`(dwMask+dwVersion+dwExtend[128],pack(1))+ `m_pString`/`m_pnTargetStringIndex`/`m_nStringStart` 字符串表指针 + `ReadString`)
- 若上面不存在,从本 SKILL.md 目录上溯 4 级再下 `src\State`:`%cd%\..\..\..\..\src\State\State.cpp`(`%cd%` 指本 SKILL.md 目录,非 CodeReviewState.md 目录)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_Base\KG3D_Base_2019.vcxproj`(`KG3D_StateFile.cpp` 在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_Base\KG3D_StateFile.cpp` 的 `KG3D_LoadStateFileData`(`:396`,读 `KG3D_STATEFILE_HEADER` → 从 `dwExtend[0-5]` 取 state/behavior/condition 数 + stringStart/endStateID → 顺序调 6 段 `_LoadState`/`_LoadBehavior`/`_LoadCondition`/`_LoadStateRelations`/`_LoadBehaviorRelations`/`_LoadConditionRelations`)
- **per-state 读取(逐版本同步的真正落点)**:`...\KG3D_StateFile.cpp` 的 `_LoadState`(`:80`,读 nID+dwVersion+model/ani(ReadString)+nStartStateID/fPlaySpeed/bLoopAni + `if(>=0x01)`nAniOffset + `if(>=0x02)`socketNum+循环(socketName/Mesh/Mtl/Ani 各 ReadString + `if(>=3)`fScale) + `if(>=0x04)`nOutSideInheritID)。**state 的 `dwVersion` 分支都在这里**(§2.2)。
- **behavior/condition 段(复刻不读,§2.3)**:`_LoadBehavior`(`:195`,只读 nType/nID/version,**无路径**)、`_LoadCondition`(`:219`,nType/nID/version + 按 nType switch 读数值,**无路径**)。复刻注释掉这两段是安全的(不漏抽)。
- **结构/枚举口径**:`KG3D_STATEFILE_HEADER`/`KG3D_STATEFILE_SUB_STATE`/`KG3D_STATEFILE_SUB_SOCKET` 等在引擎 `KG3D_StateFile.h`(经 include 解析,本机未必能直接 Read;以 `KG3D_StateFile.cpp` 字段访问反推字节数,与复刻 `State.cpp`/`State.h` 核对)。
- **读写基准**:引擎 `KG3D_StateFile.cpp` 的 `SaveToFile`(若存在)反推 reader 字节数;字符串表布局(`dwExtend[4]`=stringStart,字符串按 index 偏移取)。

对标源总览:
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层遍历 | `KG3D_LoadStateFileData`(`KG3D_StateFile.cpp:396`) | `State::ReadFile`(`State.cpp:146`) |
| 文件头 | `KG3D_STATEFILE_HEADER`(dwExtend[0-5]) | `FileHeader`(dwExtend[0-4],`State.h`) |
| state 段 | `_LoadState`(`:80`) | `State::KState_Load`(`State.cpp:18`)+`_LoadStates`(`:74`) |
| behavior 段 | `_LoadBehavior`(`:195`,无路径) | (复刻注释掉 `_LoadBehaviors`,`:101`,有意不读) |
| condition 段 | `_LoadCondition`(`:219`,无路径) | (复刻注释掉 `_LoadConditions`,`:121`,有意不读) |
| 字符串表 | `_ReadString(pStringData,pStringOffsetStart,nIndex)`(`:64`) | `State::ReadString(nIndex)`(`State.cpp:8`) |

> **State 调用路径(同 kmsc/krl/SRScene,reader 工厂分派)**:`Jx3SvnHookCheckTool.exe` → `Jx3ResFileReaderAPI`(reader 工厂按扩展名分派,大小写不敏感)→ `ProcessState`(`Jx3ResFileReaderAPI.cpp:313`,`return new kg_state::State()`)→ `State::ReadFile`。`AddFileType("state", ...)` 在 `Jx3ResFileReaderAPI.cpp:159`(注册名小写,磁盘 `.state` 也小写)。依赖路径经 `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

---

## 2. 差异比对法（每轮第一步）

引擎 `KG3D_LoadStateFileData` 读 `KG3D_STATEFILE_HEADER` → 从 `dwExtend[0-5]` 取 state/behavior/condition 数 + stringStart(`dwExtend[4]`)+ endStateID(`dwExtend[5]`,version>=1)→ 设字符串表指针 → 顺序调 6 段。复刻 `State::ReadFile` 同构(读 `FileHeader` → 从 `dwExtend[0-4]` 取数+stringStart → 设 `m_pString`/`m_pnTargetStringIndex` → 只调 `_LoadStates`,注释掉 behavior/condition)。

⚠️ **差异重点有三个,缺一不可**:
1. **文件头 dwExtend 布局层**(§2.1)——`dwExtend[0-5]` 各槽含义,引擎改槽位含义/加新槽 → 复刻取错 state 数/stringStart → 全错位。
2. **per-state 版本分支层**(§2.2,重点,普遍落后来源)——`_LoadState`/`KState_Load` 的 `dwVersion` 决定读几个字段(当前 `>=0x01` nAniOffset、`>=0x02` socket 段、`>=0x03`(socket 内)fScale、`>=0x04` nOutSideInheritID)。引擎加 `0x05+` 而复刻没跟 → state 字段错位、model/ani/socket 路径读错位/漏抽。
3. **只读 state 段的边界**(§2.3)——复刻只读 state 段、不读 behavior/condition/relation 段。⚠️ 这是**有意的**(behavior/condition 无路径),但要比对确认 behavior/condition 段**确实不含路径**;若引擎未来给 behavior/condition 加了路径字段,复刻就要补读(否则漏抽)。

⚠️ **比对口径关键:区分"字节布局差异"与"运行时逻辑差异"**(同 tani/krl/SRScene):
- **字节布局差异**(改变 `Reference`/`SkipData`/`_ReadBuffer` 读多少字节):复刻**必须对齐**——版本分支缺/字节数不对/字段顺序变,后续错位。这是 §2.2 比对重点。
- **运行时逻辑差异**(读了字段后存进结构/设默认值/算 fScale=1.0,不改字节):复刻只抽路径、不跑状态机逻辑,**不需要同步**——如引擎 `pState->pSockets[i].fScale = 1.0f`(默认值)、`strcpy_s` 存字符串,复刻用 `ReadString`+`OnReadResourceFileByGBK` 登记即可,不算落后。
- **判定法**:看该差异是否改变"读了几个字节/按什么顺序读"。改变字节=要对齐;只改运行时行为=复刻跳过即可。

### 2.1 文件头 dwExtend 布局层
- 引擎 `KG3D_STATEFILE_HEADER`:读 `sizeof(KG3D_STATEFILE_HEADER)`,从 `dwExtend` 取各槽。当前两侧槽位:
  | dwExtend 槽 | 引擎 | 复刻(`State.cpp:158-162`) |
  |---|---|---|
  | [0] | dwStateNum | nStateNum |
  | [1] | dwBehaviorNum | nBehaviorNum(取了但不用,behavior 段不读) |
  | [2] | dwConditionNum | nConditionNum(取了但不用) |
  | [3] | nStartStateID | nStartStateID(取了但不用) |
  | [4] | dwStringOffsetStart(stringStart) | m_nStringStart(字符串表起点,关键) |
  | [5] | nEndStateID(version>=1 时) | (复刻不取,不需要) |
- `dwMask`/`dwVersion`:复刻不校验(注释掉 `dwVersion>=1`),引擎 `dwVersion>=1` 时取 `dwExtend[5]`。⚠️ 若引擎改 `dwExtend` 槽位含义(如 stringStart 移位),复刻 `m_nStringStart` 取错 → `m_pString` 指错 → `ReadString` 全错 → 所有路径乱码/漏抽。**槽位含义是 State 最隐蔽的错位点**,比对时核 `dwExtend[4]` 仍是 stringStart。
- `FileHeader`(dwMask+dwVersion+dwExtend[128],pack(1))两侧 `sizeof(FileHeader)` 读法一致(引擎 `_ReadBuffer(&FileHeader,sizeof(KG3D_STATEFILE_HEADER))`,复刻 `Reference(sizeof(FileHeader))`)。

### 2.2 per-state 版本分支层（重点）
state 段每个 state 的 `_LoadState`(引擎 `:80`)/`KState_Load`(复刻 `:18`)按 `dwVersion` 分派。当前两侧分支:
| 段 | 引擎读 | 复刻读 | 字节 | 对齐 |
|---|---|---|---|---|
| nID | `_ReadBuffer(nID,int)` | `*pnID`(在 `_LoadStates:81` 读) | 4 | ✅ |
| version | `_ReadBuffer(dwVersion,DWORD)` | `Reference(pdwVersion,DWORD)` | 4 | ✅ |
| model | `nStringIndex(int)`→ReadString | `pnStringIndex(int)`→ReadString→OnRead | 4+str | ✅ |
| ani | `nStringIndex(int)`→ReadString | `pnStringIndex(int)`→ReadString→OnRead | 4+str | ✅ |
| nStartStateID | `_ReadBuffer(int)` | `SkipData(int)` | 4 | ✅ |
| fPlaySpeed | `_ReadBuffer(float)` | `SkipData(float)` | 4 | ✅ |
| bLoopAni | `_ReadBuffer(BOOL)` | `SkipData(BOOL)` | 4 | ✅ |
| `if(>=0x01)` | nAniOffset(int) | `SkipData(int)` | 4 | ✅ |
| `if(>=0x02)` | dwSocketNum(DWORD)+循环[socketName/Mesh/Mtl/Ani 各 nStringIndex(int)+ReadString] | pdwSocketInfoNum(DWORD)+循环[4×pnStringIndex(int),(后3个 Mesh/Mtl/Ani)OnRead,(第1个 socketName 只读不登记)] | 对齐 | ✅ |
| `if(>=0x03)`(socket 内) | fScale(float) | `SkipData(float)` | 4 | ✅ |
| `if(>=0x04)` | nOutSideInheritID(int) | `SkipData(int)` | 4 | ✅ |
| `if(>=0x05)`? | 引擎若加 → 读新字段 | 复刻缺 → **候选同步项** | 待引擎升级 |

- **差集**:引擎有 `>=0x05+`、复刻缺 = **候选同步项**。先核实新版本是否真写进 `.state`(引擎 `SaveToFile` 升版本 + 加字段)。引擎加 = 要同步:复刻补 `if(*pdwVersion>=0x05) SkipData(sizeof(新字段))`,对齐引擎 `_LoadState` 该版本读取的字节。
- ⚠️ **socket 循环里第1个 `pnStringIndex`(socketName)只读不登记**(复刻 `:45-46` 注释掉 `KG_PRINT_FILE`),后3个(Mesh/Mtl/Ani)才 `OnReadResourceFileByGBK`——与引擎一致(引擎 socketName 也只是名字,Mesh/Mtl/Ani 才是依赖)。同步新版本 socket 字段时,保持这个区分。
- ⚠️ 复刻用 `SkipData` 跳过它不需要的字段(nStartStateID/fPlaySpeed/bLoopAni/nAniOffset/nOutSideInheritID/fScale),只抽 model/ani/socket 路径——**有意的**,不算落后(同 krl/tani/SRScene 的 SkipData 折叠)。同步新版本分支时,照此法:**保证每段 `Reference`/`SkipData` 的总字节数与引擎该版本一致**,不追求逐字段读取方式相同。

### 2.3 只读 state 段的边界（State 特殊点）
- 引擎 `KG3D_LoadStateFileData` 顺序调 6 段(state/behavior/condition/3个relation)。**复刻只读 state 段**(`_LoadStates`),注释掉 `_LoadBehaviors`/`_LoadConditions`(及 relation)。
- **为何安全**:behavior/condition 段**不含路径**——引擎 `_LoadBehavior`(`:195`)/`_LoadCondition`(`:219`)**不调 `_ReadString`**(都 `UNREFERENCED_PARAMETER(pStringData)`),只读 nType/nID/version/数值。故复刻不读它们**不漏抽依赖路径**。
- **何时要改**:若引擎未来给 behavior/condition 段加了**路径字段**(ReadString),复刻就要补读对应段(否则漏抽)——届时 §2 比对会发现。当前(无路径)不必读。
- **字节边界**:复刻读 state 段时 `Reference` 流式推进,读 state 段末尾就 return;不跳 behavior/condition 字节(不需要,因为不抽它们、也不报错——文件头不校验总长度)。这与其他技能"读完整文件"不同,但 State 这样是**正确的**(只关心 state 段路径)。

> 实操:grep 引擎 `_LoadState` 的 `if(dwVersion>=` / `>= 0x` 取分支上限,与复刻 `KState_Load` 的 `if(*pdwVersion>=` 比对(§2.2);grep `KG3D_LoadStateFileData` 的 `dwExtend[` 各槽含义与复刻 `dwExtend[` 比对(§2.1);确认 behavior/condition 段无 `_ReadString`(§2.3)。区分"字节布局差异"(要对齐)与"运行时逻辑差异"(复刻跳过即可)。结论写进当轮记录(补了哪个版本分支/对应引擎文件:行)。

---

## 3. 一类信息抽取（同步时的不变量，必须守）

⚠️ **State 只抽一类:明文依赖路径**。**没有音频标签**(不跑 `SearchAudioLabel`,无 `AudioLabel.db`)、**没有数值汇总**(无 PssInfo 那样的汇总结构,别找第三类)。同步任何新版本/结构时,依赖路径抽取**必须跟着补**。**口径以字符串表 index 为信号,宁多勿漏**:凡是 `ReadString(*pnStringIndex)` 读出的字符串,就可能是外部资源路径,一律 `OnReadResourceFileByGBK` 登记,不靠字段名过滤(仅 socketName 这种"名字非路径"的故意不登记,见 §2.2)。

### 3.1 明文依赖路径（`OnReadResourceFileByGBK`，经 `ReadString` 从字符串表取）
登记接口:`OnReadResourceFileByGBK`(扫描时落 `ScanResult.db` 的 `Result` 表,`SonFile`/`SonExtName` = 依赖,`File` 以 `.state` 结尾)。复刻在 `KState_Load` 内登记:
| 来源 | 字段 | 大致行号 | 备注 |
|---|---|---|---|
| state model | `ReadString(*pnStringIndex)` → `m_szModelFileName` | `State.cpp:27` | 每 state 第1个路径(注释标 m_szModelFileName) |
| state ani | `ReadString(*pnStringIndex)` → `m_szAniName` | `:30` | 每 state 第2个路径 |
| socket mesh | `ReadString(*pnStringIndex)`(socket 循环第2个) | `:49` | `>=0x02` 的 socket 段 |
| socket mtl | `ReadString(*pnStringIndex)`(第3个) | `:52` | socket 段 |
| socket ani | `ReadString(*pnStringIndex)`(第4个) | `:55` | socket 段 |
| (socketName) | `ReadString(*pnStringIndex)`(第1个) | `:45` | **只读不登记**(名字非路径,注释掉 KG_PRINT_FILE) |

> 实测依赖类型分布:state 抽 model/ani(.mesh/.ani 等)+ socket 的 mesh/mtl/ani。多数 .state 有 model/ani,有 socket 的才多 mesh/mtl/ani。同步新版本时,确认路径读取的 `pnStringIndex` 位置未因新字段错位、`ReadString` 的 `m_nStringStart`/`m_pString` 没因 `dwExtend[4]` 错位而指错。

> 每轮同步后,逐版本自问:这个新版本/结构的 model/ani/socket 路径读取位置还对吗?`dwExtend[4]` stringStart 还对吗?(State 无音频、无数值汇总,只这一类。)

---

## 4. 构建（同 Pss,含 RUST 前置）

编译整个解决方案产出扫描器(`Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- `State.cpp` 在 `Jx3ResFileReaderAPI.vcxproj`。
- **前置:先编译 RUST 依赖工程(同 Pss §4,稳妥起见)**:`Jx3ResFileReaderAPI.vcxproj` link 依赖 `ClipLibX64.lib`/`KESMBaseX64.lib`(import lib),但 `FileParse.sln` 不含这两个工程、不会自动先编。lib 缺失/过期/换机器未编 → 链接 LNK1104 / 扫描时 `Jx3ResFileReaderAPI.dll` 加载 `GetLastError(126)`(RUST dll 没拷到 OutDir)。每轮先编:
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

全量 = 深扫 `$JX3_HD_Client\data\source\maps_source\` 下所有 `.state`(本机约 **668 个**;实测数秒/轮——文件少,扫描只读头部+按存盘长度跳字节、不 cook、多线程)。⚠️ 磁盘扩展名**小写 `.state`**(与 SRScene 的大写 `.SRScene` 不同),目录含中文路径(如 `交互表现/`),清单 GBK。

### 5.1 生成扫描清单(GBK!)
`ScanFileList_state.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 写**(UTF‑8 破坏中文)。用脚本(与其他技能共享的通用脚本):
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
# ⚠️ REPO 必须从仓库根(KResourceReader)取,勿在 x64/Release 里用 cd .. && pwd -W 取——cd .. 只退到 x64 一级,pwd -W 得到 仓库根/x64(多了一个 x64 段,即多一层),再拼 $REPO/x64/Release/logs/ScanFileList*.txt 就成了 仓库根/x64/x64/Release/logs/ScanFileList*.txt(x64 重复、文件不存在)→KResScanMgr::MainScan GetLastError(3) 扫0文件、45ms 退出。cwd 在仓库根时 pwd -W 直接对,无需 cd。
python "$REPO/.claude/skills/State代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/source/maps_source" --ext state \
  --out   "$REPO/x64/Release/logs/ScanFileList_state.txt"
```
(state 用独立清单 `ScanFileList_state.txt`。`--root "$JX3_HD_Client/data/source/maps_source"` 深扫,目录含中文,脚本按 GBK 写清单。)

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
  "$JX3_HD_Client" "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_state.txt"
```
- `ReadFileListFromSvnDB=1` → 走 `CopyDataFromWCDBList`:清单 INNER JOIN svn wc.db 取清单文件的元信息(changed_revision/date/author)填 FileList,再 `ProcessMultiThreadMain` 解析——**仍扫清单全量**(不漏文件),只是 FileList 多带 svn 元信息、多~8s 查 svn db(见 `feedback_readfilelist_fromsvndb_semantics`)。
- `bTest=1` → 测试环境,不上报。
- 工具 `setlocale(LC_ALL, ".936")`,自己处理 GBK,中文路径 OK。
- **State 调用路径**:见 §1 末尾(reader 工厂 `ProcessState` → `State::ReadFile`)。依赖路径经 `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

### 5.3 音频标签扫描
**无**。State 没有音频标签(spec 明确),不跑 `KSearchResource.exe SearchAudioLabel`,不产生 `AudioLabel.db`(同 Ani/krl/SRScene)。

### 5.4 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下最新时间戳子目录。`ls -t logs/JX3/trunk/ | head -1`。
- `Scan.log`:末尾应类似 `... INFO 日志正常关闭`。
- `ScanResult.db`(**State 不关注 Pss 表**,看这些):
  - `FileList`:扫到的文件集(应含全部 ~668 .state)。
  - `Result`:State 的依赖路径落库在这——
    - 解析失败:`ErrLevel=7` 且 `File` 以 `.state` 结尾(罕见,文件头不校验 version;失败多是文件损坏/stringStart 错位越界)。
    - 依赖路径:`File` 以 `.state` 结尾的记录,`SonFile`/`SonExtName` = 抽出的 model/ani/socket mesh/mtl/ani 依赖,`ErrLevel` 多为 3。
  - (无 state 专门"成功"表——不像 Pss 有 `Pss` 表;同 kmsc/tani/krl/SRScene。)

---

## 6. 差异对比（闭环的"看变化"）

`diff_state.py` 是**纯差异工具**(同 kmsc/Ani/tani/krl/SRScene 方案):只列修改前后数据差异,**不判断差异算回归还是改善**(好坏由报告/Claude 人工裁定)。资源对错是 `State.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报的职责,不是 diff 的职责。

每轮:改码前跑一次全量(baseline ScanResult.db),改+编译后再跑一次(current),对比:
```bash
python "$REPO/.claude/skills/State代码同步/scripts/diff_state.py" "<baseline ScanResult.db>" "<current ScanResult.db>" --knownbad "<清单,可选>"
```
- **无 `--audiolabel`**(State 无音频,同 Ani/krl/SRScene)。
脚本输出(纯差异,中性):
- **changed**:两侧都解析成功,但依赖集变了(中性,不判好坏)。如修复版本错位导致 model/ani/socket 依赖变化会列在此。
- **appeared**:current 新进(baseline 失败/未扫到)——如修复版本外漏抽。
- **disappeared**:baseline 有、current 不在了(需关注,可能回归)。
- **still_failing**:两侧都失败(`ErrLevel=7` .state)。与 `--knownbad` 交集 = 预期坏文件;其余待人工裁定。
- **new_fail**:baseline 没扫到、current 却失败(同清单下一般不出现,出现即异常)。
- **stable**:两侧都成功且依赖集完全相同。
- (diff 比一类:解析失败集 `Result` `ErrLevel=7` .state + 依赖路径集 `Result` `File=.state` 的 `SonFile`;**无音频对比**)
- exit code:0=正常(差异已列);1=异常(`new_fail` 非空);2=输入异常。**差异本身不导致 exit1**。

**如何裁定差异**:
- `changed`/`appeared` 里属本轮目标(如同步 `>=0x05` 后新版本 state 抽到 model/ani)= 预期改善,通过。
- `changed` 里属不该碰的(如本该有的 model 依赖莫名没了)= 回归,回滚重来。
- `disappeared`/`new_fail` = 需关注,逐个排查。

**整个闭环终止** = §2 差异比对无待同步项 且 diff 列出的差异全部裁定为"预期"(无意外 `disappeared`/`new_fail`/非目标 `changed`) 且 无 `still_failing` 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经你核实(打开文件看是否截断/损坏)后,记进 `--knownbad`,后续不再当回归。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查(6 项:4 环境变量+MSBuildTool+wc.db),任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成全量 state 清单(--root $JX3_HD_Client/data/source/maps_source --ext state)→ 跑扫描器(§5.2,ReadFileListFromSvnDB=1)得 baseline ScanResult.db → 存路径
          (State 无音频,不跑 SearchAudioLabel)
B. 比对:  按 §2 三层(文件头 dwExtend 布局/per‑state 版本分支/只读 state 段边界)比对复刻↔引擎,列当轮待同步项
          (重点:KState_Load 的 dwVersion 分支上限(§2.2,>=0x01/0x02/0x03/0x04);先核实新版本是否真序列化进 .state;
           区分"字节布局差异"与"运行时逻辑差异";确认 behavior/condition 段仍无路径(§2.3))
C. 改码:  改 State.cpp/State.h(UTF-8,Edit/Write 安全)同步该版本/结构;
          同步时逐条核 §3 一类信息(model/ani/socket 路径)是否补齐;每段 Reference/SkipData 总字节数要与引擎该版本一致
D. 编译:  §4 先编 RUST 依赖(KESMBase/ClipLib,§4 前置)→ 再 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C(LNK1104查遗留进程或RUST lib没编)
E. 测试:  用 baseline 同一份清单 → 跑扫描器(ReadFileListFromSvnDB=1)得 current ScanResult.db
          (无音频扫描)
F. 判据:  diff_state.py baseline vs current
          - 有意外差异(disappeared/new_fail/非目标 changed) → 回滚本轮改动,回到 B
          - 差异全部裁定为预期 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 差异全部预期 → 完成
          写报告 UpdateCodeState.md(§9),再汇报
```

> **只有真正改了代码才写报告**(§9)。三层已对齐、没改码(如纯健康基线检查),不写报告、只在对话里说明。

护栏(同 Pss/kmsc/Ani/tani/krl/SRScene):
- **迭代上限:最多 8 轮**。8 轮仍未清零或反复异常,停止并汇报当前状态(别死循环)。
- **B 编译错优先**:编译不过绝不进测试。
- **C 回滚要干净**:有意外差异时把 `State.cpp`/`State.h` 恢复到本轮改前状态(改前 `cp` 备份到临时目录最稳)。
- **D 编码**:源码 UTF-8 可 Edit/Write;`ScanFileList_state.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **E 全量是默认**:~668 文件/轮,实测数秒(见 §5),不慢。想对单个新版本先快速试错,可用 `regen_scanlist.py --subset` 缩小清单;但终止判据仍以全量无意外差异为准,子集只用于迭代试错。
- **F 一类信息**:每轮同步后核 §3 一类(model/ani/socket 路径)是否补齐——这是"假成功"主要来源(State 无音频、无数值汇总,只这一类;特别注意 `dwExtend[4]` stringStart 错位会让所有 `ReadString` 路径乱码/漏抽)。
- **G 不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户，同 Pss/kmsc/Ani/tani/krl/SRScene）

1. 同步了哪些版本/结构(逐项:引擎文件:行 → 复刻文件:行,补了哪个 state `dwVersion` 分支 + 对应 SkipData + model/ani/socket 路径登记)。
2. 编译状态 + 测试范围(全量 ~668,耗时)。
3. 差异对比:baseline vs current 的 `changed/appeared/disappeared/still_failing/new_fail` 计数;known-bad 清单。
4. 终止结论:差异是否清零、差异是否全部预期;撞上限则说明卡在哪轮/哪个版本。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后(类比 `CodeReviewKMSC` 的截断判断法),给出下一步。

---

## 9. 对比测试报告（落盘 UpdateCodeState.md）

按 `CodeReviewState.md` §5/§6 要求,真正改了代码后,闭环收尾把报告写到:
`项目路径\x64\Release\logs\UpdateCodeState.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(同 Pss 但**不关注 Pss 表**,重点是 `Result`/`FileList`;**无 AudioLabel**,不跑音频扫描,同 Ani/krl/SRScene):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`;没有 = `Jx3SvnHookCheckTool.exe` 执行失败。
2. **ScanResult.db 逐表对比**:表 `FileList`/`Result` 内容——相同、不同,及不同原因(**不关注 Pss 表**)。

### 9.1 报告生成方式(脚本 + Claude 分工,同 Pss/kmsc/Ani/krl/SRScene)
```bash
REPO="$(pwd -W)"
python "$REPO/.claude/skills/State代码同步/scripts/gen_report_state.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "$REPO/x64/Release/logs/UpdateCodeState.md"
```
- 脚本逐表对比 ScanResult(FileList/Result,**不关注 Pss 表**)+ 检查 Scan.log,输出 md 片段(UTF‑8)。
- **无 `--audiolabel`**(State 无音频,同 Ani/krl/SRScene)。
- 脚本只给数字和样本,**"代码改动说明"和"不同原因"由 Claude 据本次改动补写**在脚本片段之上。

### 9.2 UpdateCodeState.md 结构(参考 Pss/kmsc/Ani/krl/SRScene 范式)
```
# State 代码修改前后对比测试报告
> 生成日期 / 对比 baseline vs current / 全量 ~668 state

## 一、本次代码改动            ← Claude 写(引擎文件:行 → 复刻文件:行,补了什么)
## 二、前后对比结果             ← gen_report_state.py 脚本片段(Scan.log + ScanResult[不关注Pss])
## 三、不同原因分析             ← Claude 写(逐表解释为什么不同,与本次改动的因果)
## 四、终止结论                 ← Claude 写(差异清零/无回归/是否撞上限;遗留建议)
```
- "二"由脚本 `>>` 追加;"一/三/四"由 Claude 写在片段上下。
- 报告 UTF-8(用 Write/Edit),**不是 GBK**——中文要正常显示。

**⚠️ "三、不同原因分析"必须详细说明差异来源**(不只列数字):
- 对每个有差异的表/字段,**说清差异从哪来**——是本次代码改动导致的(如"同步 state `>=0x05` 后,新版本 state 的 model/ani 依赖从错位漏抽变为正确抽到")、还是数据本身变动、还是工具行为差异。
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

# 生成全量 GBK state 清单(深扫 data/source/maps_source 下 .state,小写扩展名,含中文目录)
python "$REPO/.claude/skills/State代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/source/maps_source" --ext state \
  --out   "x64/Release/logs/ScanFileList_state.txt"

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
  "$JX3_HD_Client" "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_state.txt"

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1

# 差异对比(失败集+依赖,纯差异不判好坏,无音频)
python "$REPO/.claude/skills/State代码同步/scripts/diff_state.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>"

# 生成对比报告片段(ScanResult[不关注Pss]+Scan.log,无 AudioLabel)
python "$REPO/.claude/skills/State代码同步/scripts/gen_report_state.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodeState.md"   # Claude 再补"代码改动/不同原因/结论"于其上
```
