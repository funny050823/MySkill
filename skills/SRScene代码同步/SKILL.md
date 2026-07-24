---
name: SRScene代码同步
description: 把 SRScene 复刻解析器(SRScene::ReadFile)与引擎原函数(KSRScene::LoadFromFile)对齐,修复"复刻落后引擎"导致的 .SRScene(场景响应)解析失败/漏抽依赖路径。当用户提到 srscene 解析失败、场景响应解析失败、SRScene 复刻落后引擎、KSRScene/KSREntity 对齐、entity 版本分支未同步、srscene 漏抽依赖路径(SMTemplate)、或想让 KResourceReader 正确解析新版本 .SRScene 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到差异清零且无意外差异为止。
---

# SRScene 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `SRScene::ReadFile`(`kg_SRScene::SRScene`)是引擎 `KSRScene::LoadFromFile` 的**复刻**,解析 `.SRScene` 场景响应文件。`.SRScene` 描述一个场景里的若干 SREntity(场景实体),每个 entity 带位置/缩放/旋转 + 版本相关字段 + 可选的状态机模板(SMTemplate)引用。复刻只"读得动 + 抽资源检查需要的依赖路径",不跑场景响应逻辑。

引擎用**每 entity 的 `dwVersion` 字段**做版本分派(`KSREntity::LoadFromFile` 内 `if(dwVersion>=1)` / `>=2`),每升一版加一个字段;文件头 `dwVersion` 固定为 0。复刻一旦没跟上引擎新增的 V3+,或版本分支字段没同步,遇到新版本的 `.SRScene` 就会**解析失败**或**漏抽依赖路径**(SMTemplate)——错位后 SMTemplate 路径读错位/漏抽。

⚠️ **与 Pss 的关键差异(决定技能不同)**:
1. **只抽一类:明文依赖路径**(SMTemplate 文件),经 `OnReadResourceFileByGBK` 登记。**没有音频标签**(不跑 `KSearchResource.exe SearchAudioLabel`,无 AudioLabel.db)、**没有数值汇总**(无 PssInfo 那样的汇总结构,别找第三类)。同 krl/Ani 的"无音频"形态,但 SRScene 依赖路径很少(只有 SMTemplate 一种,且仅 `pbHaveSMTemplate` 为真时才有)。
2. **调用路径同 kmsc/krl**(reader 工厂):`AddFileType("srscene", &ProcessSrScene)`(`Jx3ResFileReaderAPI.cpp:162`)→ `ProcessSrScene` → `new kg_SRScene::SRScene` → `SRScene::ReadFile`。⚠️ 注册名是小写 `srscene`,但磁盘文件扩展名是 **`.SRScene`(大写)**;工具按扩展名分派时大小写不敏感(Windows + 工具 `_stricmp`),故 `.SRScene` 能命中 `srscene` 注册。清单收集 `--ext srscene`(Python `endswith` 用 lower 比较)能匹配 `.SRScene`。
3. **结构自维护**:`HeaderSRScene.h` **自维护** `FileHeader`(dwMask+dwVersion+dwExtend[128]),非 include 引擎头(同 Ani/krl)。落后风险在**文件头常量/版本分支/读取序列**,不在 include 同步。⚠️ 引擎头(`KSRScene.h`/`KSREntity.h` 等)经 include 路径解析,本机未必能直接 Read 到;比对时以引擎 `KSRScene.cpp`/`KSREntity.cpp` 的 `Read(...)`/字段访问反推字节数,与复刻 `SRScene.cpp` 逐一核对。
4. **顶层 default 软失败**:复刻 `ReadFile` 的 `KG_PROCESS_ERROR(pFileHeader->dwVersion == 0)` 是**文件头版本校验**——文件头 `dwVersion` 必须 ==0,否则 `KG_PROCESS_ERROR(false)` 失败;entity 内 `dwVersion` 的 `>=1`/`>=2` 是**版本分支**(读不同字段),无 default(超过当前版本的字段复刻不读,等后续版本字段被引擎加时再跟)。落后多表现为"漏抽/错位"(新版本 entity 字段没跳、SMTemplate 路径读错位),少表现为"解析失败"(文件头 version≠0 或 entity 数据错位导致越界)。

本技能把"对齐复刻与引擎"做成**全自动闭环**(同 Pss/kmsc/Ani/tani/krl):比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 有意外差异就回滚,直到差异清零。过程中**守住一类信息抽取口径**(明文依赖路径)。

> 工作模式:**全自动闭环**(同 Pss/kmsc/Ani/tani/krl),中途不必征询用户,收尾汇报。护栏见 §7。仅在 windows 下执行。

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
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`SRScene.cpp` 编进此工程,以 `..\src\SRScene\SRScene.cpp` 引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\SRScene\SRScene.cpp`（顶层 `ReadFile`,**简洁,主要落点**）
- `项目路径\src\SRScene\HeaderSRScene.h`（**自维护** `FileHeader`(dwMask+dwVersion+dwExtend[128])+ `SRSCENE_FILEMASK` 常量,非 include 引擎——落后风险在文件头常量/版本分支/读取序列,同 Ani/krl 的自维护头）
- `项目路径\src\SRScene\SRScene.h`(`SRScene` 类)
- 若上面不存在,从本 SKILL.md 目录上溯 4 级再下 `src\SRScene`:`%cd%\..\..\..\..\src\SRScene\SRScene.cpp`(`%cd%` 指本 SKILL.md 目录,非 CodeReviewSRScene.md 目录)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Module\KG3DSceneResponse\KG3DEntitySystem_2019.vcxproj`(`KSRScene.cpp`/`KSREntity.cpp` 在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Module\KG3DSceneResponse\KSRScene.cpp` 的 `KSRScene::LoadFromFile`(`:277`,读 `FileHeader` → 校验 `dwVersion==0` → `_LoadSREntity`)
- **per‑entity 读取(逐版本同步的真正落点)**:`...\KG3DSceneResponse\KSREntity.cpp` 的 `KSREntity::LoadFromFile`(`:776`,读 `dwVersion` → float3×2+vscal/qRotation → `if(dwVersion>=1)` 读 DisplayLevel → `if(dwVersion>=2)` 读 NpcID)。**entity 的 `dwVersion` 分支都在这里**(§2.2)。
- **entity 段读取**:`KSRScene.cpp:575` `_LoadSREntity`(读 `dwEntitySize` → 循环 `dwEntityID` + `pEntity->LoadFromFile` + `bHaveSMTemplate` + `MAX_PATH` SMTemplate 路径)。
- **读写基准**:`KSREntity.cpp` 的 `SaveToFile`(`:757`,`s_dwVersion = 2`,注释"Version2:据点争夺战属性需求NPCID")反推 reader 字节数——当前写盘 entity 版本 = 2。

对标源总览:
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层遍历 | `KSRScene::LoadFromFile`(`KSRScene.cpp:277`) | `SRScene::ReadFile`(`SRScene.cpp:26`) |
| 文件头校验 | `fileHeader.dwVersion==0`(`:307`) | `pFileHeader->dwVersion==0`(`SRScene.cpp:33`) |
| entity 段 | `KSRScene::_LoadSREntity`(`:575`) | `SRScene::ReadFile` 内 entity 循环(`:35`) |
| per‑entity 读取 | `KSREntity::LoadFromFile`(`KSREntity.cpp:776`) | `SRScene::ReadFile` 内 `pEntity->LoadFromFile` 段(`:46`) |
| 文件头常量 | `SRSCENE_FILE_VERSION`(`KSRScene.cpp:17`)/mask | `SRSCENE_FILEMASK=MAKEFOURCC('S','R','S','\0')`(`SRScene.cpp:9`)+`FileHeader` |

> **SRScene 调用路径(同 kmsc/krl,reader 工厂分派)**:`Jx3SvnHookCheckTool.exe` → `Jx3ResFileReaderAPI`(reader 工厂按扩展名分派,**大小写不敏感**)→ `ProcessSrScene`(`Jx3ResFileReaderAPI.cpp:323`,`return new kg_SRScene::SRScene()`)→ `SRScene::ReadFile`。`AddFileType("srscene", ...)` 在 `Jx3ResFileReaderAPI.cpp:162`(注册名小写,匹配磁盘 `.SRScene` 大写)。依赖路径经 `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

---

## 2. 差异比对法（每轮第一步）

引擎 `LoadFromFile` 读 `FileHeader`(校验 `dwMask==SRSCENE_FILEMASK`、`dwVersion==0`)→ `_LoadSREntity`:读 `dwEntitySize` → 循环 `dwEntitySize` 次:读 `dwEntityID` → `pEntity->LoadFromFile(pFile)`(内部按 entity `dwVersion` 分派)→ 读 `bHaveSMTemplate` → 若有读 `MAX_PATH` SMTemplate 路径并注册。复刻 `SRScene::ReadFile` 同构(读 header → 校验 → entity 循环 → 每 entity 读 version+跳字段+版本分支 → `pbHaveSMTemplate` → 有则读 MAX_PATH 登记)。

⚠️ **差异重点有两个,缺一不可**:
1. **per‑entity 版本分支层**(§2.2)——**普遍的落后来源**:entity 的 `dwVersion` 决定读几个字段(当前 `>=1` 读 DisplayLevel、`>=2` 读 NpcID)。引擎加 `V3+`(新版本加字段)而复刻没跟 `if(dwVersion>=3)` → 该版本 entity 字段错位、SMTemplate 路径读错位/漏抽。这是 SRScene 最核心的落后风险点。
2. **结构/常量层**(§2.3)——`FileHeader`(mask/version/Extend[128])、entity 段布局(dwEntitySize/dwEntityID/各字段顺序)、SMTemplate 段(BOOL + MAX_PATH)。引擎改结构/常量而复刻 `HeaderSRScene.h`/`SRScene.cpp` 没跟 → 错位。

⚠️ **比对口径关键:区分"字节布局差异"与"运行时逻辑差异"**(同 tani/krl):
- **字节布局差异**(改变 `Reference`/`SkipData`/`Read` 读多少字节):复刻**必须对齐**——版本分支缺/字节数不对/字段顺序变,后续错位。这是 §2.2 比对重点。
- **运行时逻辑差异**(读了字段后做运算/注册 SMTemplate/AttachStateMachine,不改字节):复刻只抽路径、不跑场景响应逻辑,**不需要同步**——如引擎 `RegisterTempalte`/`AttachStateMachineTemplate`/`m_bNative=TRUE`,复刻用 `OnReadResourceFileByGBK` 登记路径即可,不算落后。
- **判定法**:看该差异是否改变"读了几个字节/按什么顺序读"。改变字节=要对齐;只改运行时行为=复刻跳过即可。

### 2.1 文件头层
- `SRSCENE_FILEMASK = MAKEFOURCC('S','R','S','\0')`(复刻 `SRScene.cpp:9`)。与引擎 `SRSCENE_FILE_VERSION`/mask 常量核对(引擎 `KSRScene.cpp:17`)。
- 文件头 `dwVersion` 固定 ==0(引擎 `_ASSERTE(fileHeader.dwVersion==0)` `:307`,复刻 `SRScene.cpp:33`)。⚠️ 这是**文件头版本**,与 entity 的 `dwVersion` 不是一回事——文件头恒 0,entity 版本可升。
- `FileHeader` 结构(dwMask+dwVersion+dwExtend[128],pack(1))两侧字段/大小一致,否则 `Reference(sizeof(FileHeader))` 读错、后续全错位。

### 2.2 per‑entity 版本分支层（重点）
entity 段每个 entity 的 `KSREntity::LoadFromFile`(`KSREntity.cpp:776`)按 `dwVersion` 分派。当前两侧分支:
| 分支 | 引擎读 | 复刻读 | 当前对齐 |
|---|---|---|---|
| 基础(所有版本) | `dwVersion(DWORD)` + `m_vTrans(float*3)` + `m_vscal(float*3)` + `m_qRotation(float*4)` | `Reference(pdwVersion,DWORD)` + `SkipData(float*3)`×2 + `SkipData(float*4)` | ✅ 字节数对齐(复刻跳过 vTrans/vscal/qRotation) |
| `if(dwVersion>=1)` | 读 `m_dwDisplayLevel(DWORD)` | `SkipData(sizeof(DWORD))` | ✅ |
| `if(dwVersion>=2)` | 读 `m_dwNpcID(DWORD)` | `SkipData(sizeof(DWORD))` | ✅ |
| `if(dwVersion>=3)`? | 引擎若加 → 读新字段 | 复刻缺 → **候选同步项** | 待引擎升级 |

- 引擎当前写盘版本 `s_dwVersion=2`(`KSREntity.cpp:757`,"Version2:据点争夺战属性需求NPCID")。复刻 `>=1`/`>=2` 已覆盖。
- **差集**:引擎有 `>=3+`、复刻缺 = **候选同步项**。先核实新版本是否真写进 `.SRScene`(引擎 `SaveToFile` 升 `s_dwVersion` + 加 `fwrite`)。引擎升 s_dwVersion = 新版本格式落地 = 要同步:复刻补 `if(*pdwVersion>=N) SkipData(sizeof(新字段))`,对齐引擎 `LoadFromFile` 该版本读取的字节。
- ⚠️ 复刻用 `SkipData` 跳过它不需要的字段(vTrans/vscal/qRotation/DisplayLevel/NpcID),只抽 SMTemplate 路径——**这是有意的**,不算落后(同 krl/tani 的 SkipData 折叠)。同步新版本分支时,照此法:**保证每段 `Reference`/`SkipData` 的总字节数与引擎该版本一致**,不追求逐字段读取方式相同。

### 2.3 结构/常量层
- `FileHeader`(dwMask+dwVersion+dwExtend[128],pack(1)):复刻 `HeaderSRScene.h` 与引擎 `KSRScene.cpp` 的 `fileHeader` 用法核对(读 `sizeof(FileHeader)`,Extend[128] 大小要对)。
- entity 段布局:`dwEntitySize(DWORD)` → 循环 [`dwEntityID(DWORD)` + `pEntity->LoadFromFile` 内容 + `bHaveSMTemplate(BOOL)` + (有则)`MAX_PATH` 路径]。复刻 `SRScene.cpp:35-71` 与引擎 `_LoadSREntity:575-631` 逐段核对。
- SMTemplate 段:`bHaveSMTemplate(BOOL)` + `MAX_PATH*sizeof(char)` 路径。复刻 `Reference(pszFile, MAX_PATH*sizeof(char))` + `OnReadResourceFileByGBK` 与引擎 `Read(szSMTempalte, sizeof(char)*MAX_PATH)` + `RegisterTempalte` 对齐。

> 实操:grep 引擎 `KSREntity::LoadFromFile` 的 `if(dwVersion>=` 取分支上限,与复刻 `SRScene.cpp` 的 `if(*pdwVersion>=` 比对(§2.2);grep `KSRScene::_LoadSREntity` 的 `Read(...sizeof...)` 顺序与复刻 entity 循环 `Reference/SkipData` 顺序比对(§2.3);区分"字节布局差异"(要对齐)与"运行时逻辑差异"(复刻跳过即可)。结论写进当轮记录(补了哪个版本分支/对应引擎文件:行)。

---

## 3. 一类信息抽取（同步时的不变量，必须守）

⚠️ **SRScene 只抽一类:明文依赖路径**。**没有音频标签**(不跑 `SearchAudioLabel`,无 `AudioLabel.db`)、**没有数值汇总**(无 PssInfo 那样的汇总结构,别找第三类)。同步任何新版本/结构时,SMTemplate 路径抽取**必须跟着补**。**口径以宏为信号,宁多勿漏**:凡是 `Reference(..., MAX_PATH*sizeof(char))` 读的字段,就可能是外部资源路径,一律 `OnReadResourceFileByGBK` 登记,不靠字段名过滤。

### 3.1 明文依赖路径（`OnReadResourceFileByGBK`）
登记接口:`OnReadResourceFileByGBK`(扫描时落 `ScanResult.db` 的 `Result` 表,`SonFile`/`SonExtName` = 依赖,`File` 以 `.SRScene`/`.srscene` 结尾)。
| 来源 | 字段 | 大致行号 | 备注 |
|---|---|---|---|
| entity 段 `pbHaveSMTemplate` 为真 | `pszFile`(SMTemplate 路径,MAX_PATH) | `SRScene.cpp:68-69` | 每个 entity 最多一个 SMTemplate;`bHaveSMTemplate` 为真才读/登记 |

> 实测依赖:SRScene 依赖路径**只有 SMTemplate 一种**(状态机模板文件),且仅 `bHaveSMTemplate==TRUE` 的 entity 才有。多数 entity 无 SMTemplate → 多数 .SRScene 可能无依赖记录(正常)。同步新版本时,确认 SMTemplate 路径读取仍在 `pbHaveSMTemplate` 为真分支内、字节位置未因新版本字段错位。

> 每轮同步后,逐版本自问:这个新版本/结构的 SMTemplate 路径读取位置还对吗?字节没因新字段错位?(SRScene 无音频、无数值汇总,只这一类。)

---

## 4. 构建（同 Pss,含 RUST 前置）

编译整个解决方案产出扫描器(`Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- `SRScene.cpp` 在 `Jx3ResFileReaderAPI.vcxproj`。
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

全量 = 深扫 `$JX3_HD_Client\data\source\maps\` 下所有 `.SRScene`(本机约 **434 个**;实测数秒/轮——扫描只读头部+按存盘长度跳字节、不 cook、多线程,文件少很快)。

### 5.1 生成扫描清单(GBK!)
`ScanFileList_srscene.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 写**(UTF‑8 破坏中文)。用脚本(与其他技能共享的通用脚本):
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
# ⚠️ REPO 必须从仓库根(KResourceReader)取,勿在 x64/Release 里用 cd .. && pwd -W 取——cd .. 只退到 x64 一级,pwd -W 得到 仓库根/x64(多了一个 x64 段,即多一层),再拼 $REPO/x64/Release/logs/ScanFileList*.txt 就成了 仓库根/x64/x64/Release/logs/ScanFileList*.txt(x64 重复、文件不存在)→KResScanMgr::MainScan GetLastError(3) 扫0文件、45ms 退出。cwd 在仓库根时 pwd -W 直接对,无需 cd。
python "$REPO/.claude/skills/SRScene代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/source/maps" --ext srscene \
  --out   "$REPO/x64/Release/logs/ScanFileList_srscene.txt"
```
(srscene 用独立清单 `ScanFileList_srscene.txt`。`--ext srscene` 收集时 Python `endswith` 用 lower 比较,能匹配磁盘大写 `.SRScene`。`--root "$JX3_HD_Client/data/source/maps"` 深扫 maps 目录。)

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
  "$REPO/x64/Release/logs/ScanFileList_srscene.txt"
```
- `ReadFileListFromSvnDB=1` → 走 `CopyDataFromWCDBList`:清单(ScanFileListInput)INNER JOIN svn wc.db 取清单文件的元信息(changed_revision/date/author)填 FileList,再 `ProcessMultiThreadMain` 解析——**仍扫清单全量**(不漏文件),只是 FileList 多带 svn 元信息、多~8s 查 svn db。
- `bTest=1` → 测试环境,不上报。
- 工具 `setlocale(LC_ALL, ".936")`,自己处理 GBK,中文路径 OK。
- **SRScene 调用路径**:见 §1 末尾(reader 工厂 `ProcessSrScene` → `SRScene::ReadFile`,大小写不敏感)。依赖路径经 `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

### 5.3 音频标签扫描
**无**。SRScene 没有音频标签(spec 明确),不跑 `KSearchResource.exe SearchAudioLabel`,不产生 `AudioLabel.db`(同 Ani/krl)。

### 5.4 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下最新时间戳子目录。`ls -t logs/JX3/trunk/ | head -1`。
- `Scan.log`:末尾应类似 `... INFO 日志正常关闭`。
- `ScanResult.db`(**SRScene 不关注 Pss 表**,看这些):
  - `FileList`:扫到的文件集(应含全部 ~434 .SRScene)。
  - `Result`:SRScene 的依赖路径落库在这——
    - 解析失败:`ErrLevel=7` 且 `File` 以 `.SRScene`/`.srscene` 结尾(文件头 version≠0 或 entity 数据错位越界)。
    - 依赖路径:`File` 以 `.SRScene` 结尾的记录,`SonFile`/`SonExtName` = 抽出的 SMTemplate 依赖,`ErrLevel` 多为 3。**多数 .SRScene 可能无 SMTemplate → 无依赖记录**(正常,不算漏抽)。
  - (无 srscene 专门"成功"表——不像 Pss 有 `Pss` 表;同 kmsc/tani/krl。)

---

## 6. 差异对比（闭环的"看变化"）

`diff_srscene.py` 是**纯差异工具**(同 kmsc/Ani/tani/krl 方案):只列修改前后数据差异,**不判断差异算回归还是改善**(好坏由报告/Claude 人工裁定)。资源对错是 `SRScene.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报的职责,不是 diff 的职责。

每轮:改码前跑一次全量(baseline ScanResult.db),改+编译后再跑一次(current),对比:
```bash
python "$REPO/.claude/skills/SRScene代码同步/scripts/diff_srscene.py" "<baseline ScanResult.db>" "<current ScanResult.db>" --knownbad "<清单,可选>"
```
- **无 `--audiolabel`**(SRScene 无音频,同 Ani/krl)。
脚本输出(纯差异,中性):
- **changed**:两侧都解析成功,但依赖集变了(中性,不判好坏)。如修复版本错位导致 SMTemplate 依赖变化会列在此。
- **appeared**:current 新进(baseline 失败/未扫到)——如修复版本外漏抽。
- **disappeared**:baseline 有、current 不在了(需关注,可能回归)。
- **still_failing**:两侧都失败(`ErrLevel=7` .SRScene)。与 `--knownbad` 交集 = 预期坏文件;其余待人工裁定。
- **new_fail**:baseline 没扫到、current 却失败(同清单下一般不出现,出现即异常)。
- **stable**:两侧都成功且依赖集完全相同。
- (diff 比一类:解析失败集 `Result` `ErrLevel=7` .SRScene + 依赖路径集 `Result` `File=.SRScene` 的 `SonFile`;**无音频对比**)
- exit code:0=正常(差异已列);1=异常(`new_fail` 非空);2=输入异常。**差异本身不导致 exit1**。

**如何裁定差异**:
- `changed`/`appeared` 里属本轮目标(如同步 V3 后新版本 entity 的 SMTemplate 抽到)= 预期改善,通过。
- `changed` 里属不该碰的(如本无 SMTemplate 的 entity 莫名出了依赖)= 回归,回滚重来。
- `disappeared`/`new_fail` = 需关注,逐个排查。

**整个闭环终止** = §2 差异比对无待同步项 且 diff 列出的差异全部裁定为"预期"(无意外 `disappeared`/`new_fail`/非目标 `changed`) 且 无 `still_failing` 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经你核实(打开文件看是否截断/损坏)后,记进 `--knownbad`,后续不再当回归。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查(6 项:4 环境变量+MSBuildTool+wc.db),任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成全量 srscene 清单(--root $JX3_HD_Client/data/source/maps --ext srscene)→ 跑扫描器(§5.2)得 baseline ScanResult.db → 存路径
          (SRScene 无音频,不跑 SearchAudioLabel)
B. 比对:  按 §2 三层(文件头/per‑entity 版本分支/结构)比对复刻↔引擎,列当轮待同步项
          (重点:entity dwVersion 分支上限(§2.2,KSREntity::LoadFromFile);先核实新版本是否真序列化进 .SRScene;区分"字节布局差异"与"运行时逻辑差异")
C. 改码:  改 SRScene.cpp/HeaderSRScene.h(UTF-8,Edit/Write 安全)同步该版本/结构;
          同步时逐条核 §3 一类信息(SMTemplate 路径)是否补齐;每段 Reference/SkipData 总字节数要与引擎该版本一致
D. 编译:  §4 先编 RUST 依赖(KESMBase/ClipLib,§4 前置)→ 再 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C(LNK1104查遗留进程或RUST lib没编)
E. 测试:  用 baseline 同一份清单 → 跑扫描器得 current ScanResult.db
          (无音频扫描)
F. 判据:  diff_srscene.py baseline vs current
          - 有意外差异(disappeared/new_fail/非目标 changed) → 回滚本轮改动,回到 B
          - 差异全部裁定为预期 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 差异全部预期 → 完成
          写报告 UpdateCodeSRScene.md(§9),再汇报
```

> **只有真正改了代码才写报告**(§9)。三层已对齐、没改码(如纯健康基线检查),不写报告、只在对话里说明。

护栏(同 Pss/kmsc/Ani/tani/krl):
- **迭代上限:最多 8 轮**。8 轮仍未清零或反复异常,停止并汇报当前状态(别死循环)。
- **B 编译错优先**:编译不过绝不进测试。
- **C 回滚要干净**:有意外差异时把 `SRScene.cpp`/`HeaderSRScene.h` 恢复到本轮改前状态(改前 `cp` 备份到临时目录最稳)。
- **D 编码**:源码 UTF-8 可 Edit/Write;`ScanFileList_srscene.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **E 全量是默认**:~434 文件/轮,实测数秒(见 §5),不慢。想对单个新版本先快速试错,可用 `regen_scanlist.py --subset` 缩小清单;但终止判据仍以全量无意外差异为准,子集只用于迭代试错。
- **F 一类信息**:每轮同步后核 §3 一类(SMTemplate 路径)是否补齐——这是"假成功"主要来源(SRScene 无音频、无数值汇总,只这一类;注意多数 entity 无 SMTemplate 是正常的,别误判为漏抽)。
- **G 不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户，同 Pss/kmsc/Ani/tani/krl）

1. 同步了哪些版本/结构(逐项:引擎文件:行 → 复刻文件:行,补了哪个 entity `dwVersion` 分支 + 对应 SkipData + SMTemplate 路径登记)。
2. 编译状态 + 测试范围(全量 ~434,耗时)。
3. 差异对比:baseline vs current 的 `changed/appeared/disappeared/still_failing/new_fail` 计数;known-bad 清单。
4. 终止结论:差异是否清零、差异是否全部预期;撞上限则说明卡在哪轮/哪个版本。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后(类比 `CodeReviewKMSC` 的截断判断法),给出下一步。

---

## 9. 对比测试报告（落盘 UpdateCodeSRScene.md）

按 `CodeReviewSRScene.md` §5/§6 要求,真正改了代码后,闭环收尾把报告写到:
`项目路径\x64\Release\logs\UpdateCodeSRScene.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(同 Pss 但**不关注 Pss 表**,重点是 `Result`/`FileList`;**无 AudioLabel**,不跑音频扫描,同 Ani/krl):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`;没有 = `Jx3SvnHookCheckTool.exe` 执行失败。
2. **ScanResult.db 逐表对比**:表 `FileList`/`Result` 内容——相同、不同,及不同原因(**不关注 Pss 表**)。

### 9.1 报告生成方式(脚本 + Claude 分工,同 Pss/kmsc/Ani/krl)
```bash
REPO="$(pwd -W)"
python "$REPO/.claude/skills/SRScene代码同步/scripts/gen_report_srscene.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "$REPO/x64/Release/logs/UpdateCodeSRScene.md"
```
- 脚本逐表对比 ScanResult(FileList/Result,**不关注 Pss 表**)+ 检查 Scan.log,输出 md 片段(UTF‑8)。
- **无 `--audiolabel`**(SRScene 无音频,同 Ani/krl)。
- 脚本只给数字和样本,**"代码改动说明"和"不同原因"由 Claude 据本次改动补写**在脚本片段之上。

### 9.2 UpdateCodeSRScene.md 结构(参考 Pss/kmsc/Ani/krl 范式)
```
# SRScene 代码修改前后对比测试报告
> 生成日期 / 对比 baseline vs current / 全量 ~434 SRScene

## 一、本次代码改动            ← Claude 写(引擎文件:行 → 复刻文件:行,补了什么)
## 二、前后对比结果             ← gen_report_srscene.py 脚本片段(Scan.log + ScanResult[不关注Pss])
## 三、不同原因分析             ← Claude 写(逐表解释为什么不同,与本次改动的因果)
## 四、终止结论                 ← Claude 写(差异清零/无回归/是否撞上限;遗留建议)
```
- "二"由脚本 `>>` 追加;"一/三/四"由 Claude 写在片段上下。
- 报告 UTF-8(用 Write/Edit),**不是 GBK**——中文要正常显示。

**⚠️ "三、不同原因分析"必须详细说明差异来源**(不只列数字):
- 对每个有差异的表/字段,**说清差异从哪来**——是本次代码改动导致的(如"同步 entity V3 后,新版本 .SRScene 的 SMTemplate 依赖从错位漏抽变为正确抽到")、还是数据本身变动、还是工具行为差异。
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

# 生成全量 GBK srscene 清单(深扫 data/source/maps 下 .SRScene;--ext srscene 匹配大写)
python "$REPO/.claude/skills/SRScene代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/source/maps" --ext srscene \
  --out   "x64/Release/logs/ScanFileList_srscene.txt"

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
  "$REPO/x64/Release/logs/ScanFileList_srscene.txt"

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1

# 差异对比(失败集+依赖,纯差异不判好坏,无音频)
python "$REPO/.claude/skills/SRScene代码同步/scripts/diff_srscene.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>"

# 生成对比报告片段(ScanResult[不关注Pss]+Scan.log,无 AudioLabel)
python "$REPO/.claude/skills/SRScene代码同步/scripts/gen_report_srscene.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodeSRScene.md"   # Claude 再补"代码改动/不同原因/结论"于其上
```
