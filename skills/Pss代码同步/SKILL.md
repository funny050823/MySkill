---
name: Pss代码同步
description: 把 Pss 复刻解析器(Pss::ReadFile)与引擎原函数(KG3D_ParticleFileData::LoadFromFile)对齐,修复"复刻落后引擎"导致的 .pss 解析失败/漏抽数据。当用户提到 pss 解析失败、pss 漏抽资源/音频/特效、复刻落后引擎、新发射器类型未同步、Pss::ReadFile 与引擎对齐、或想让 KResourceReader 正确解析新类型 .pss 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到无回归且无新失败为止。
---

# Pss 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `Pss::ReadFile` 是引擎 `KG3D_ParticleFileData::LoadFromFile` 的**复刻**。复刻只为"读得动 + 抽资源检查需要的信息",不跑渲染。问题是:引擎会持续新增/修改发射器类型(`PARSYS_LAUNCHER_*`)、模块(`KG3D_ParticleModule::ReadData` 派生)、结构体(`KG3D_PARSYS_*_STATIC_DATA`)。复刻一旦没跟上,遇到新类型的 `.pss` 就会**解析失败**或**漏抽重要数据**(明文路径/音频标签/特效数据)——典型如 `PARSYS_LAUNCHER_FORCEFIELDQUOTE` 当年没同步那次。

本技能把"对齐复刻与引擎"做成**全自动闭环**:比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 不通过就回滚再来,直到差异清零且无回归。过程中**始终守住三类信息抽取口径**,否则"解析成功"也是假成功。

> 工作模式已与用户约定为**全自动闭环**:你定位差异、直接改 `Pss.cpp`、编译、测试、对比、循环,中途不必征询用户;只在收尾(完成/撞到迭代上限/无法继续)时汇报。护栏见 §7。

---

## 1. 锁定路径（别取错）

> **前置环境检查(进技能第一步先做,缺了直接报错、不继续)**:本技能依赖一组 Windows 环境变量(在系统里配置,非本会话临时设),编译/对标都要用。进 §7 闭环 A 步前,先逐个核实存在:
> | 环境变量 | 必需 | 用途 | 缺失后果 |
> |---|---|---|---|
> | `JX3ENGINE_Sword3` | **必** | 引擎源码根(`...\Source\KG3DEngineDX11\...`),对标口径 + 编译 include/lib | 找不到引擎文件、编译失败 |
> | `JX3ENGINE_BASE` | **必** | 编译 include/lib(`$(JX3ENGINE_BASE)\include` 等) | 编译失败 |
> | `JX3ENGINE_DevEnv` | **必** | 部分工程编译用(`$(JX3ENGINE_DevEnv)/Include` 等) | 编译失败 |
> | `JX3_HD_Client` | **必** | client 测试数据根(全量扫描/音频扫描输入),指向 `...\sword3-products\trunk\client` 目录,内容以 GB 计、不会为空 | 全量扫描无数据 |
> | `MSBuildTool` | **必** | MSBuild.exe 路径(编译 `FileParse.sln`),指向 `...\2019\...\Bin\MSBuild.exe` | 编译失败 |
> | svn `wc.db` | **必** | `$JX3_HD_Client/../.svn/wc.db` 或 `$JX3_HD_Client/.svn/wc.db` 之一(client 上级是 svn 副本根→前者;client 自身是副本根→后者),exe 要求 `PathFileExistsA(pszDBFile)` 真 | 扫描器报"参数错误" |
> - 检查命令(bash):`for v in JX3ENGINE_Sword3 JX3ENGINE_BASE JX3ENGINE_DevEnv JX3_HD_Client; do [ -d "${!v}" ] && echo "$v OK=${!v}" || echo "$v 缺失/无效,技能终止"; done; [ -f "$MSBuildTool" ] && echo "MSBuildTool OK=$MSBuildTool" || echo "MSBuildTool 缺失/无效,技能终止"; WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"; [ -f "$WCDB" ] && echo "wc.db OK=$WCDB" || echo "wc.db 异常:\$JX3_HD_Client/../.svn/wc.db 和 \$JX3_HD_Client/.svn/wc.db 都不存在,技能终止"`(`JX3_HD_Client` 即 client 测试数据目录,查它存在即可,无需另查 client 路径;`MSBuildTool` 是 exe 文件用 `[ -f ]` 查;`wc.db` 上级/本级 .svn 必须存在一个)
> - 任一**必需**项缺失 → 报错并停止,不要继续到后面才发现编译/对标失败。

> **项目路径(仓库根)**:`KResourceReader` 仓库根 = 本 SKILL.md 上溯 4 级 = Claude 执行技能时的工作目录(Primary working directory)。下文复刻文件、构建、测试输出路径均相对此项目路径:
> - 给 Claude 读的说明路径写作 `项目路径\src\Pss\...`(Claude 知道项目路径 = 当前工作目录,可直接 Read)。
> - bash 命令块用 `REPO="$(pwd -W)"` 取项目路径的 Windows 绝对路径(`pwd -W` 输出 `D:/...` 正斜杠格式,exe 能接受),块内用 `$REPO/...`;传给 exe 的文件路径(ScanFileList/AudioLabel.db)必须用这种绝对路径(exe 内部会 `SetCurrentDirectoryA` 到 client,相对路径会失效)。

复刻侧（你要改的，UTF‑8 BOM，Edit/Write 安全）:
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`Pss.cpp`/`HeaderPss.h`/`Pss.h` 编进此工程,以 `..\src\Pss\*` 引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\Pss\Pss.cpp`（主）
- `项目路径\src\Pss\HeaderPss.h`
- `项目路径\src\Pss\Pss.h`
- 若上面不存在,从 **本 SKILL.md 所在目录** 上溯(本 SKILL.md 在 `.../KResourceReader/.claude/skills/Pss代码同步/`,上溯 4 级 `..` 到仓库根 `KResourceReader`,再下 `src\Pss`):`%cd%\..\..\..\..\src\Pss\Pss.cpp`。⚠️ 注意 `%cd%` 指本 SKILL.md 目录,不是 `CodeReviewPss.md` 目录(后者只上溯 1 级 `\..\src`,路径不同,别混用)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleSystem_2019.vcxproj`(`KG3D_ParticleFileData.cpp` 等在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleFileData.cpp` 里的 `KG3D_ParticleFileData::LoadFromFile`
- **发射器类型枚举(口径来源)**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\InternalPublish\Include\ParticleSystem\IKE3D_ParticleType.h`
  - ⚠️ 该文件在 `InternalPublish\Include\ParticleSystem\` 下,**不在** `...\Component\KG3D_ParticleSystem\` 下,别取错。`PARSYS_LAUNCHER_*` / `PARSYS_CT_*` 枚举都在这。
- **结构体口径**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleFileDeclare.h`(`KG3D_PARSYS_*_STATIC_DATA`、各 block 结构)
- **per‑type 读取逻辑(逐类型同步的真正落点)**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleLauncher.cpp` + `KG3D_ParticleLauncher.h`,各 `KG3D_ParticleXxxLauncher::ReadData`。原文档没列这俩,但同步新发射器类型时必须看它。
- 抽取信息结构:`项目路径\include\IJx3ResFileReader.h` 第 ~387 行 `PssInfo`。

对标源总览(扩展口径,逐项都要用上):
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层遍历 | `KG3D_ParticleFileData::LoadFromFile` | `Pss::ReadFile` |
| 元素块分派 | `gs_ParticleSystemLoadHelpFunction[FEID]`(函数表) | `gs_ParticleSystemLoadHelpFunction[FEID]`(`Pss.cpp:31`) |
| 发射器块 | `_PARSYS_ReadParticleLauncherBlock` | `Pss::_PARSYS_ReadParticleLauncherBlock` |
| 预计算 | `KG3D_ParticlePreCompute::ReadData` | `Pss::KG3D_ParticlePreCompute_ReadData` |
| 发射器类型 | 各 `KG3D_ParticleXxxLauncher::ReadData`(`KG3D_ParticleLauncher.cpp`) | `Pss::KG3D_ParticleXxxLauncher_ReadData`(`Pss.cpp` 内 switch) |
| 模块 | 各 `KG3D_ParticleModule::ReadData` 派生 | `Pss::KG3D_ParticleModule_ReadData` |

---

## 2. 差异比对法（每轮第一步）

引擎元素级用**函数表** `gs_ParticleSystemLoadHelpFunction[KG3D_PARSYS_FEID_COUNT]` 分派(枚举 `KG3D_PARSYS_FEID_*`);发射器块内再 `switch(pBlock->byLauncherType)` 按 `PARSYS_LAUNCHER_*` 分派到各 per‑type `ReadData`。差异就从这两层 + 结构体层查。

### 2.1 元素块层(FEID)
- 引擎:`KG3D_ParticleFileData.cpp` 里 `gs_ParticleSystemLoadHelpFunction[]` 的下标与函数;`KG3D_PARSYS_FEID_COUNT` 来自 `KG3D_ParticleFileDeclare.h`。
- 复刻:`Pss.cpp:31` 的同表。
- 差异:引擎多了新 FEID block(或某 block 函数体读取序列变了)→ 复刻要补/对齐。

### 2.2 发射器类型层(重点)
- 枚举全集:从 `IKE3D_ParticleType.h` 取所有 `PARSYS_LAUNCHER_*`(排除 `PARSYS_LAUNCHER_COUNT`/`PARSYS_LAUNCHER_TYPE` 这类哨兵,以及 `PARSYS_LAUNCHER_SIGNIFICANCE`——那是手机核心发射器**标志位**,不是独立类型,复刻用 `byMobileLauncher`/`m_nLauncherSignificance` 计数器体现)。
- 复刻 switch:`Pss.cpp` 内 `switch(pBlock->byLauncherType)`(约 `:1076` 起以及 `:1125` 起的第二处)。
- 差集:引擎有、复刻 switch 缺的 case = **候选同步项**。
- ⚠️ **"switch 缺 case" ≠ "必须同步"**:逐类型核实它**是否真被序列化进 `.pss`**。编辑器/运行时专用、从不写进文件的类型不需要同步。核实办法:在 `KG3D_ParticleFileData.cpp` 的 `_PARSYS_ReadParticleLauncherBlock` 及对应 `KG3D_ParticleXxxLauncher::ReadData`/`SaveToFile` 里确认该类型有"从文件读"的路径;有 `SaveToFile` 写入才有 `ReadData` 读取的必要。只对"会被写进 .pss"的类型同步。
- 对每个确认要同步的类型:去 `KG3D_ParticleLauncher.cpp` 找 `KG3D_ParticleXxxLauncher::ReadData`,**按字节顺序**把读取序列搬进复刻,套用复刻现有 per‑type 函数风格(自由函数 `KG3D_ParticleXxxLauncher_ReadData`)。

### 2.3 模块层
- 引擎:各 `KG3D_ParticleModule::ReadData` 派生(`KG3D_ParticleLauncher.cpp`/相关)。
- 复刻:`Pss::KG3D_ParticleModule_ReadData` 的 `switch(*pnClassID)`/`switch(*pdwParamType)` 分派(约 `:491`/`:574`)。
- 差异:新增模块 class/param 类型 → 复刻补 case + 对应读取。模块读取常含 `PARSYS_CT_*` 循环参数(如 `PARSYS_CT_PARTICLE_LIFETIME` 第2参循环次数 → `vdwLoopCount`),见 §3.3。

### 2.4 结构体层
- 引擎:`KG3D_ParticleFileDeclare.h` 的 `KG3D_PARSYS_*_BLOCK` / `KG3D_PARSYS_*_STATIC_DATA`。
- 复刻:`HeaderPss.h`/`Pss.h` 的对应结构。
- 差异:引擎结构新增字段/改大小(版本号分支 `pFileData->dwVersion >= PARSYS_VERSION_xx` 里加读取)→ 复刻结构体与版本分支都要同步,**否则后续字段错位**,这类错位最隐蔽(不报错但读错)。

> 实操:用 grep 各取两侧的 `PARSYS_LAUNCHER_*`/`KG3D_PARSYS_FEID_*`/`PARSYS_CT_*`/结构体名做集合差,再人工(你)逐项按上面四层核实。把结论写进当轮记录(改了哪个类型、补了哪些字段、对应引擎文件:行)。

---

## 3. 三类信息抽取（同步时的不变量，必须守）

"解析成功"不够,还得抽信息供资源检查/入库。同步任何新类型/结构时,这三类**必须跟着补**,否则就是漏抽。特效数据写进 `m_pssInfo`(`IJx3ResFileReader.h:387` `PssInfo`)。**口径以宏为信号,宁多勿漏**:凡是见到 `MAX_PATH`/`FILENAME_MAX` 宏参与 `Reference(..., sizeof(char)*MAX_PATH)` 读取,就可能是外部资源路径,一律捞出来登记,不靠字段名过滤。

### 3.1 明文路径引用（登记 `OnReadResourceFileByGBK(路径, ...)`）
已知登记点(`Pss.cpp` 行号会随代码变,以当前文件为准):
| 来源块 | 字段 | 大致行号 | 备注 |
|---|---|---|---|
| 材质块 `KG3D_MaterialBase_LoadFromBuffer` | 材质定义名 `szDefineName` | ~293 | |
| 材质块 | 贴图文件名 `pszFile` | ~353 | 仅 texture 循环登记 |
| 材质块 | float/vec/color 参数名 | ~361 等 | 当前注释掉只跳过,仍是 `MAX_PATH` 读取,属**候选**,需确认是否登记 |
| Track 块 `_PARSYS_ReadParticleTrackBlock` | `byTrackFileName` | ~1386 | |
| 声音引用发射器 `KG3D_ParticleSoundQuoteLauncher_ReadData` | `bySoundName` | ~1216 | 仅 `.ogg/.wav/.mp3` 结尾登记 |
| Mesh 发射器 `KG3D_ParticleMeshLauncher_ReadData` | `byMeshName` | ~1233 | 仅 `PARSYS_PARTICLE_SHAPE_CUSTOM` |
| GPU Mesh 发射器 `KG3D_CollectMeshLauncher_ReadData` | `byStringName` | ~1251 | |
| 力场引用发射器 `KG3D_ParticleForceFieldQuoteLauncher_ReadData` | `szFieldFilePath` | ~1267 | .fga 力场路径,非空才登记 |
| 模型引用发射器 `KG3D_ParticleMeshQuoteLauncher_ReadData` | `byAnimationName/byMeshName/byMtlInsPackName` | ~1317-1319 | |

### 3.2 音频标签（`KGShare::SoundLabel::Instance().AddWwiseEvent` / `AddFmod`）
凡是涉及音效标签的一律捞,不得漏。新增带音频的发射器/模块必须补登记。
| 来源块 | 调用 | 大致行号 | 类型 |
|---|---|---|---|
| WWISE 发射器 `KG3D_ParticleWwiseLauncher_ReadData` | `AddWwiseEvent(GetSrcFile(), byEvent)` | ~1189 | `PARSYS_LAUNCHER_WWISE` |
| 声音引用发射器 `KG3D_ParticleSoundQuoteLauncher_ReadData` | `AddFmod(GetSrcFile(), bySoundName)` | ~1210 | `PARSYS_LAUNCHER_SOUNDQUOTE` |

> **音频标签可前后对比(纳入判据)**:`AddWwiseEvent`/`AddFmod` 落库到独立的 `AudioLabel.db` 的 `File(File,EventName,AudioFile)` 表(由 `KSearchResource.exe SearchAudioLabel` 全库扫产出,见 §5.4)。改码前后各跑一份、按 `.pss` 过滤比三元组集合,`audio_removed`(baseline 有 current 无)=漏抽音频=回归。

### 3.3 特效数据（写 `m_pssInfo` / 成员计数器）
`PssInfo` 字段与来源:
| 字段 | 含义 | 来源 | 大致行号 |
|---|---|---|---|
| `nBBoxX/Y/Z` | 包围盒=AABBoxMax−AABBoxMin(取整) | GeneralInfo 块 | ~130-132 |
| `dwParticleNumMax` | 最大粒子数 | GeneralInfo `dwMaxParticle` | ~134 |
| `nMaterialNum` | 材质数 | 材质块每块 +1 | ~204 |
| `vnNumPlay` | 发射器播放次数,0=无限循环 | 每 launcher `nNumPlay` | ~1019 |
| `nMobileLauncher` | 移动端发射器数 | `byMobileLauncher==1||2` | ~1025 |
| `nLaucherNumMax` | 发射器总数 | 每 launcher 块 +1 | ~1163 |
| `vdwLoopCount` | `PARSYS_CT_PARTICLE_LIFETIME` 模块第2参(j==1)循环次数,0=无限 | 模块循环 | ~586 |
| `nMeshQuoteNum` | 模型引用发射器数 | 模型引用块 | ~1324 |
| `nMeshQuoteVertexNum` | 累计各引用 mesh 顶点数,取不到置 −1 | `GetMeshNumVertices` 现读 .mesh 文件头 | ~1335 |
| `nTrackCnt` | Track 块数 | Track 块每块 +1 | ~1387 |

非 `PssInfo` 成员计数器:`m_nLauncherSignificance`/`m_nLauncherSignificanceLess2`(~1027/1030)、`m_nMobileLodCnt[4]`(`FORMBOBILELODCOUNT` 开关,~1039)、`m_ppMeshFile[]`(~1323)、`MESH_MAX_CNT=512`(~140,`nMeshQuoteNum` 超出报错)。

> 每轮同步后,逐类型自问:这个新类型的 `MAX_PATH` 读取登记了吗?有音频吗(AddWwiseEvent/AddFmod)?它的发射器数/材质数/循环数/包围盒/Track 写进 `m_pssInfo` 了吗?三类都要有结论。

---

## 4. 构建

编译整个解决方案产出扫描器(测试要用的 `Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- MSBuild:用环境变量 `%MSBuildTool%`(本机 = `C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe`),见 §1 前置环境检查。
- 命令(在仓库根 `项目路径` 执行;Claude 执行技能时 cwd 本就在仓库根,用相对的 `FileParse.sln` 即可):
  ```bash
  "$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
  ```
  - bash 下 MSBuild 的 `/` 参数要写成 `//`(防 bash 当成路径)。或用 `//m` 并行。
- **不要用 `Build.cmd`**:它带 `svn up` / git 推送 / PE 版本核验 / "svn 版本不超前就 skip build" 的副作用,不适合本闭环。本闭环只要 `FileParse.sln` rebuild 出新 exe。
- 判定:退出码 0 且 `x64\Release\Jx3SvnHookCheckTool.exe` 更新时间刷新即编译成功。编译失败 → 看 `logs\Build.Sln.log`(若用 `Build.cmd`)或 MSBuild stdout,先修编译错再继续(别带着编译错去测试)。
- PE 版本自检:本闭环跳过(那是发布管线的事)。如需,见 `CheckPEVersion.ps1`。

---

## 5. 测试（全量）

用户已定**每轮全量**。全量 = 扫 `%JX3_HD_Client%\data\source\other\` 下所有 `.pss`(本机约 **4.16 万**个)。**实测约 10-15 秒/轮**(扫描只读文件头+跳字节、不 cook、多线程),并不慢,无需提示预计耗时。想对单个新类型先快速试错,可用 `--subset` 缩小清单(见 §7 护栏 E)。

### 5.1 生成扫描清单(GBK!)
`ScanFileList.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 工具写它**(Write 按 UTF‑8 会破坏中文路径)。用脚本:
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
python ".claude/skills/Pss代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/source/other" \
  --out   "$REPO/x64/Release/logs/ScanFileList.txt"
```
脚本遍历 `--root` 收集 `*.pss`,按 GBK+CRLF 写出。传 `--subset <目录或清单文件>` 只跑子集。

### 5.2 跑扫描器(关键:ReadFileListFromSvnDB=0)
现有 `x64\Release\logs\Jx3LocalResScanTool.cmd` 里 `ReadFileListFromSvnDB=1` 会去 svn db 读**改动文件**,不是全量。全量要置 `0`,让工具走 `ScanByFileList(ScanFileList.txt)` 精确扫清单里的文件。`.cmd` 是 GBK,别用 Edit/Write 改它——直接带环境变量调 exe:
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO/x64/Release"
# svn wc.db:client 上级是 svn 副本根→../.svn,自身是副本根→.svn,两者必须存在一个(§1 前置已查,此为单独跑本块时的兜底)
WCDB="$JX3_HD_Client/../.svn/wc.db"
if [ ! -f "$WCDB" ]; then WCDB="$JX3_HD_Client/.svn/wc.db"; fi
if [ ! -f "$WCDB" ]; then echo "异常:svn wc.db 不存在(\$JX3_HD_Client/../.svn/wc.db 和 \$JX3_HD_Client/.svn/wc.db 都没有),技能终止"; exit 1; fi
ReadFileListFromSvnDB=0 bTest=1 ForDebug=0 \
  ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList.txt"
```
- `bTest=1` → 测试环境,不上报。
- 第 4 个参数(`argc==4`)走 `MainScan(ClientPath, DBFile, ScanList, bReadFileListFromSvnDB)`;`ReadFileListFromSvnDB=0` + ScanList 是文件 → `ScanByFileList`,精确扫清单。
- 工具 `setlocale(LC_ALL, ".936")`,自己处理 GBK,中文路径 OK。

### 5.3 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下**最新时间戳子目录**(如 `20260721_173011\`)。
- `Scan.log`:看进程是否正常结束,最后一行应类似 `17:30:21.866 TID(15708) INFO 日志正常关闭`。
- `ScanResult.db`(SQLite3):核心数据表——
  - **`Pss`**:每行一个解析成功的 pss,字段 `FilePath,LaucherNumMax,MobileLauncherMax,ParticleNumMax,MaterialNum,MeshQuoteNum,MeshQuoteVertexNum,BBoxX,BBoxY,BBoxZ,TrackCnt,SkipIgnore`(=§3.3 特效数据)。
  - **`PssLoop`**:每行一个 pss 的 `nLauncherCnt,nUnlimitLauncherLoopCnt,nParticleCnt,nUnlimitLoopParticleCnt`(`vnNumPlay`/`vdwLoopCount` 计数)。
  - **`Result`**:问题记录;`ErrLevel=7` 即**解析失败**(视图 `ToolReadFileErr`/`DetailReport`)。pss 文件解析失败 = 扫了但没进 `Pss` 表,且/或 `Result` 里有 `ErrLevel=7` 且文件名 `.pss`。
  - `FileList`/`FileListInput`:扫描到的文件集。
- 查最新目录可用:`ls -t x64/Release/logs/JX3/trunk/ | head -1`。

### 5.4 跑音频标签扫描(改码前后各一次,路径不同!)
音频标签(§3.2 的 AddWwiseEvent/AddFmod)不落 `ScanResult.db`,落独立的 `AudioLabel.db`,由 `KSearchResource.exe SearchAudioLabel` **全库扫**(扫 `data\movie .kmsc` + `data\source\other .pss` + `data\source .tani`,不按 ScanFileList,~13 秒,实测)。pss 的音频标签在 `File` 表 `.pss` 部分(本机约 2900 行)。
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO/x64/Release"
# 改码前(baseline):注意!每次跑 InitDB 会先删再建同名 db,前后必须不同文件名,否则后跑覆盖先跑、没法对比
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "$REPO/x64/Release/logs/AudioLabel_baseline.db"
# 改码后(current):换文件名
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "$REPO/x64/Release/logs/AudioLabel_current.db"
```
- `argc==4`:`argv[1]=SearchAudioLabel`,`argv[2]=client`(工具自己 `SetCurrentDirectoryA` 到此),`argv[3]=output db`。
- `AudioLabel.db` 表:`File(File,EventName,AudioFile)` 音频标签 + `LogInfo`/`NewMovieInfo`/`MovieKrlTxt`/`FilterKmsc`(kmsc 协议动画相关,pss 技能只取 `File` 表 `.pss` 部分)。
- ⚠️ **前后必须不同 db 文件名**(如上 `_baseline`/`_current`)。`SoundLabel::InitDB` 先 `DeleteFileA` 再建,同路径后跑必覆盖先跑。

---

## 6. 回归保护判据（闭环的"通过/终止"）

用户已定通过判据为**回归保护**。每轮:先**改代码前**跑一次全量当 baseline,改+编译后跑一次当 current,对比两份 `ScanResult.db`。

对比脚本(读 baseline 与 current 两个 `ScanResult.db`,比 `Pss`+`PssLoop`+解析失败集;可选 `--audiolabel` 比 `AudioLabel.db` 的 `.pss` 音频标签):
```bash
python ".claude/skills/Pss代码同步/scripts/diff_scanresult.py" \
  "<baseline.db>" "<current.db>" \
  --knownbad "<known-bad 清单,可选>" \
  --audiolabel "<AudioLabel_baseline.db>" "<AudioLabel_current.db>"
```
脚本输出:
- **regressed(回归)**:baseline 在 `Pss` 表(曾解析 OK)→ current 要么不在 `Pss`(现在解析失败),要么在但 9 字段变了。**只要 regressed 非空,本轮不通过,回滚本轮改动重来。** 理由:对一个本来就解析正确的文件,同步不该改它的抽取结果;变了就是引入了错位/漏抽。
- **audio_removed(音频回归)**:baseline 的某 `.pss` 音频三元组 `(File,EventName,AudioFile)` current 没有 = 漏抽音频。非空同样触发回滚(并进 exit code)。
- **improved(改善)**:baseline 解析失败 → current 进了 `Pss` 表。本轮目标文件应出现在这里。
- **still_failing(仍失败)**:两次都失败。与 `--knownbad` 交集 = 预期坏文件(如被截断的 .pss,见同类 `CodeReviewKMSC` 的 32KB 截断案例),不计回归;`still_failing − knownbad` = 待人工裁定的新/旧失败。
- exit code:0=无回归,1=有回归(regressed/new_fail/audio_removed 任一非空)(脚本化判断,别靠肉眼看)。

**单轮通过** = `regressed` 与 `audio_removed` 均为空 且 本轮目标文件出现在 `improved`(或该类型相关文件不再失败)。
**整个闭环终止** = 差异比对(§2)已无待同步项 且 一次全量无回归(含音频) 且 无 `still_failing` 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经你核实(打开文件看是否截断/损坏,类比 `CodeReviewKMSC` 的判断法)后,记进 `--knownbad`,后续不再当回归。

> 三类信息现在都能前后对比:§3.1 明文路径/§3.3 特效数据在 `ScanResult.db`(`Result` 依赖 + `Pss` 表),§3.2 音频标签在 `AudioLabel.db`(`File` 表)。改码前后各跑一次扫描器(§5.2)+ 一次音频扫描(§5.4),`diff_scanresult.py` 一次性比全。`--audiolabel` 可省略(只比 ScanResult),但既然音频是重点项、且 ~13 秒不慢,默认带上。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查,核实 JX3ENGINE_Sword3/JX3ENGINE_BASE 必需项 + client 目录存在;
          任一缺失 → 报错终止,不进 A
A. 基线:  regen_scanlist.py 生成全量清单 → 跑扫描器(§5.2)得 baseline ScanResult.db
          + 跑 SearchAudioLabel(§5.4)得 baseline AudioLabel.db → 存两者路径
B. 比对:  按 §2 四层比对复刻↔引擎,列出当轮要同步的项(优先级:解析失败相关的类型 > 结构体错位 > 其余)
C. 改码:  改 Pss.cpp/HeaderPss.h/Pss.h(UTF-8,Edit/Write 安全)同步该类型;
          同步时逐条核 §3 三类信息是否补齐
D. 编译:  §4 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C(不要带错测试)
E. 测试:  不重生清单(用 baseline 同一份)→ 跑扫描器得 current ScanResult.db
          + 跑 SearchAudioLabel 得 current AudioLabel.db(不同文件名!)
F. 判据:  diff_scanresult.py baseline vs current --audiolabel baseline_audio current_audio
          - regressed 或 audio_removed 非空 → 回滚本轮改动,回到 B 重新分析(可能字节顺序/字段对错了)
          - 目标文件 improved 且无回归(含音频) → 本轮通过,回到 B 看还有无待同步项
G. 终止:  B 无待同步项 且 F 无回归(含音频) 且 无非 known-bad 新失败 → 完成
          写报告 UpdateCodePss.md(§9),再汇报(§8)
```

> **只有真正改了代码才写报告**(§9)。若四层已对齐、没改码(如纯健康基线检查),不写报告、只在对话里说明。

护栏:
- **A 迭代上限:最多 8 轮**。8 轮仍未清零差异或反复回归,停止并汇报当前状态(别死循环)。
- **B 编译错优先**:编译不过绝不进测试。
- **C 回滚要干净**:regressed 时用 git/备份把 `Pss.cpp` 等恢复到本轮改前状态再重来。仓库根可 `git status`/`git diff` 取改动(注意:本仓库 `.git` 可能不在根,改前先 `cp` 备份 `src/Pss/` 三个文件到临时目录最稳)。
- **D 编码**:源码 UTF-8 可 Edit/Write;`ScanFileList.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **E 全量是默认**:~4.16 万文件/轮,实测约 10-15 秒/轮(见 §5),不慢。想对单个新类型先快速试错,可用 `regen_scanlist.py --subset` 缩小清单;但终止判据仍以全量无回归为准,子集只用于迭代试错。
- **F 三类信息**:每轮同步后必须按 §3 逐类型自检路径/音频/特效三类是否补齐——这是"假成功"的主要来源。
- **G 不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户）

完成后给:
1. 同步了哪些类型/结构(逐项:引擎文件:行 → 复刻文件:行,补了什么读取/字段/三类信息登记)。
2. 编译状态 + 测试范围(全量/子集,文件数)。
3. 回归判据:baseline vs current 的 `regressed/improved/still_failing` 计数 + `audio_removed/audio_added`;known-bad 清单。
4. 终止结论:差异是否清零、是否无回归;若撞上限,说明卡在哪轮/哪个类型。
5. 遗留建议:仍 `still_failing` 且非 known-bad 的文件,逐个判断是真坏文件还是复刻仍落后(类比 `CodeReviewKMSC` 的截断判断法),给出下一步。

---

## 9. 对比测试报告（落盘 UpdateCodePss.md）

按 `CodeReviewPss.md` §6 要求,真正改了代码后,闭环收尾时把"代码修改前后对比测试报告"写到:
`项目路径\x64\Release\logs\UpdateCodePss.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(文档硬性要求):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`;没有 = `Jx3SvnHookCheckTool.exe` 执行失败。
2. **ScanResult.db 逐表对比**:表 `FileList`/`Result`/`Pss` 内容——相同、不同,及不同原因。
3. **AudioLabel.db 逐表对比**:表 `File`/`FilterKmsc`/`LogInfo`/`MovieKrlTxt`/`NewMovieInfo` 内容——相同、不同,及不同原因。

### 9.1 报告生成方式(脚本 + Claude 分工)
机械对比由脚本做,Claude 补脚本给不出的部分:
```bash
# 脚本逐表对比 8 张表 + 检查 Scan.log,输出可直接粘进 md 的对比结果片段
python ".claude/skills/Pss代码同步/scripts/gen_report_pss.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-audio "<baseline AudioLabel.db>" --current-audio "<current AudioLabel.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodePss.md"
```
- 脚本输出的是 md 片段(UTF‑8),含 Scan.log 状态 + 8 表"相同/不同计数 + 不同样本"。
- 脚本只给数字和样本,**给不出"代码改动说明"和"不同原因"**——这两部分由 Claude 据本次改动与回归分析,写在脚本片段**之上**(报告开头):本次改了哪些文件/函数/行(引擎文件:行 → 复刻文件:行)、为何这样改、各表不同的原因(如"`Result` current 少 3 行 = 本轮修复了 3 个误报" / "`Pss` 某 `FilePath` 的 `LaucherNumMax` +1 = 新类型发射器被正确计数")。

### 9.2 UpdateCodePss.md 结构(参考 `Docs/ToolUpdateDiff2.md` 范式)
```
# Pss 代码修改前后对比测试报告
> 生成日期: <YYYY-MM-DD>   对比: 改码前 baseline vs 改码后 current

## 一、本次代码改动            ← Claude 写(引擎文件:行 → 复刻文件:行,补了什么)
## 二、前后对比结果             ← gen_report_pss.py 脚本片段(Scan.log + 8表)
## 三、不同原因分析             ← Claude 写(逐表解释为什么不同,与本次改动的因果)
## 四、终止结论                 ← Claude 写(差异清零/无回归/是否撞上限;遗留建议)
```
- "二"由脚本 `>>` 追加;"一/三/四"由 Claude 用 Write/Edit 写在脚本片段上下。
- 顺序建议:Claude 先 Write 写"一/三/四"骨架(把"二"留占位),再 `gen_report_pss.py >>` 把对比片段插到"二"位置;或先跑脚本生成"二"片段,再 Edit 在其上补"一/三/四"。
- ⚠️ 报告是 UTF‑8(用 Write/Edit),**不是 GBK**——与 `ScanFileList.txt`/`.cmd` 不同,这里中文要正常显示,Edit/Write 安全。

---

## 附:快速命令速查

```bash
# 仓库根:Claude 执行技能时 cwd 本就在仓库根(Primary working directory),pwd -W 直接取到。
# 若 cwd 不在仓库根,先 cd 到仓库根(SKLILL.md 上溯 4 级)再取,否则 REPO 会错。
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO"

# 生成全量 GBK 清单
python ".claude/skills/Pss代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client/data/source/other" \
  --out   "x64/Release/logs/ScanFileList.txt"

# 编译
"$MSBuildTool" \
  FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal

# 全量扫描(ReadFileListFromSvnDB=0 走 ScanByFileList)
cd "x64/Release"
WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"
[ -f "$WCDB" ] || { echo "异常:svn wc.db 两个候选都不存在,技能终止"; exit 1; }  # 上级/本级 .svn 必须存在一个(§1 前置已查,此为兜底)
ReadFileListFromSvnDB=0 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList.txt"

# 音频标签扫描(改码前后用不同 db 文件名!InitDB 会先删同名 db)
cd "x64/Release"
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "x64/Release/logs/AudioLabel_baseline.db"   # current 轮换 _current.db

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1   # → 20260721_173011 之类

# 回归对比(特效+解析失败+音频三类一次比全)
python ".claude/skills/Pss代码同步/scripts/diff_scanresult.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>" \
  --audiolabel "<baseline AudioLabel.db>" "<current AudioLabel.db>"

# 生成对比测试报告片段(8表+Scan.log,UTF-8 md,追加进 UpdateCodePss.md)
python ".claude/skills/Pss代码同步/scripts/gen_report_pss.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-audio "<baseline AudioLabel.db>" --current-audio "<current AudioLabel.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodePss.md"   # Claude 再补"代码改动/不同原因/结论"于其上
```
