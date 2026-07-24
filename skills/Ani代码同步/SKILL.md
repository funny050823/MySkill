---
name: Ani代码同步
description: 把 Ani 复刻解析器(Ani::ReadFile)与引擎原函数(KG3D_Animation::LoadFromFile)对齐,修复"复刻落后引擎"导致的 .ani 解析失败/漏抽骨骼数·顶点数。当用户提到 ani 解析失败、动画解析失败、Ani 复刻落后引擎、骨骼/顶点动画漏抽、Ani::ReadFile 与引擎对齐、或想让 KResourceReader 正确解析新类型 .ani 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到无回归且无新失败为止。
---

# Ani 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `Ani::ReadFile`(`kg_ani::Ani`)是引擎 `KG3D_Animation::LoadFromFile` 的**复刻**,解析 `.ani` 动画文件,抽出动画类型/骨骼数/顶点数/是否抽帧/文件版本 mask 供资源检查。引擎新增/改动画类型(`KG3D_ANIMATION_TYPE`)、文件 mask(`ANI_FILE_MASK_*`)、结构体时,复刻没跟上就会**漏抽**(骨骼/顶点数读错、mask 落 default)。

⚠️ 与 Pss/Kmsc 不同:**Ani 无音频标签**;抽取信息只有 4 个成员(不是三类);Ani::ReadFile **不经 reader 工厂 `AddFileType`**,而经 `KResChecker→GetAniInfo→KBase::GetAniInfo→Ani::ScanFile→ReadFile` 调用(见 §5)。复刻 `default` 不 `KG_PROCESS_ERROR`(**不硬失败**,落 default 只是漏抽该类型信息,不挂整个文件)——所以 ani 落后多表现为"漏抽/读错",少表现为"解析失败"。

本技能把"对齐复刻与引擎"做成**全自动闭环**(同 Pss):比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 不通过回滚,直到差异清零且无回归。

> 工作模式:**全自动闭环**(同 Pss),中途不必征询用户,收尾汇报。护栏见 §7。仅在 windows 下执行。

---

## 1. 锁定路径（别取错）

> **前置环境检查(同 Pss,进技能第一步先做,缺了直接报错、不继续)**:本技能依赖一组 Windows 环境变量(系统配置,非会话临时设),编译/对标都要用。进 §7 闭环 A 步前,先逐个核实存在:
> | 环境变量 | 必需 | 用途 | 缺失后果 |
> |---|---|---|---|
> | `JX3ENGINE_Sword3` | **必** | 引擎源码根(`...\Source\KG3DEngineDX11\...`),对标口径 + 编译 include/lib | 找不到引擎文件、编译失败 |
> | `JX3ENGINE_BASE` | **必** | 编译 include/lib(`$(JX3ENGINE_BASE)\include` 等) | 编译失败 |
> | `JX3ENGINE_DevEnv` | **必** | 部分工程编译用(`$(JX3ENGINE_DevEnv)/Include` 等) | 编译失败 |
> | `JX3_HD_Client` | **必** | client 测试数据根(全量扫描输入),指向 client 数据根目录(sword3-products 下的 client 副本),内容以 GB 计、不会为空 | 全量扫描无数据 |
> | `MSBuildTool` | **必** | MSBuild.exe 路径(编译 `FileParse.sln`),指向 `...\2019\...\Bin\MSBuild.exe` | 编译失败 |
> | svn `wc.db` | **必** | `$JX3_HD_Client/../.svn/wc.db` 或 `$JX3_HD_Client/.svn/wc.db` 之一(exe 要求 `PathFileExistsA(pszDBFile)` 真) | 扫描器报"参数错误" |
> - 检查命令(bash,同 Pss):`for v in JX3ENGINE_Sword3 JX3ENGINE_BASE JX3ENGINE_DevEnv JX3_HD_Client; do [ -d "${!v}" ] && echo "$v OK=${!v}" || echo "$v 缺失/无效,技能终止"; done; [ -f "$MSBuildTool" ] && echo "MSBuildTool OK=$MSBuildTool" || echo "MSBuildTool 缺失/无效,技能终止"; WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"; [ -f "$WCDB" ] && echo "wc.db OK=$WCDB" || echo "wc.db 异常,技能终止"`
> - 任一**必需**项缺失 → 报错并停止,不要继续到后面才发现编译/对标失败。

> **项目路径(仓库根)**(同 Pss):`KResourceReader` 仓库根 = 本 SKILL.md 上溯 4 级 = Claude 执行技能时的工作目录(Primary working directory)。说明路径写作 `项目路径\...`;bash 命令块用 `REPO="$(pwd -W)"`(Windows 绝对,exe 能接受),块内 `$REPO/...`;传 exe 的文件路径必须绝对(exe 内部 `SetCurrentDirectoryA` 到 client,相对路径失效)。Claude 执行技能 cwd 本就在仓库根,`pwd -W` 直接对。

复刻侧（你要改的，UTF‑8，Edit/Write 安全）:
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`Ani.cpp` 编进此工程,以 `..\src\Ani\Ani.cpp` 引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\Ani\Ani.cpp`（主,`Ani::ReadFile`）+ `Ani.h`（**自维护** `_ANI_FILE_HEADER`/`_BONE_ANI`/`_VERTEX_ANI`/`KG3D_ANIMATION_TYPE` 枚举/`ANI_FILE_MASK_*` 等结构,非 include 引擎——落后风险在结构/枚举值与 switch case,不在 include 同步)
- 若上面不存在,从本 SKILL.md 目录上溯 4 级再下 `src\Ani`:`%cd%\..\..\..\..\src\Ani\Ani.cpp`(`%cd%` 指本 SKILL.md 目录,非 CodeReviewAni.md 目录)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_Model\KG3D_Model_2019.vcxproj`(`KG3D_Animation.cpp` 在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_Model\KG3D_Animation.cpp` 的 `KG3D_Animation::LoadFromFile`
- **枚举口径**:`KG3D_ANIMATION_TYPE`(`ANIMATION_NONE/BONE_RTS/VERTICES/...`)在 `%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\InternalPublish\Include\Model\KG3D_Animation.h`。复刻 `Ani.h` 有副本,逐项核对(尤其引擎有 `ANIMATION_BONE_RTS_BINDPOSE_UPDATE` 而复刻副本可能缺,见 §2)。
- **结构口径**:`_ANI_FILE_HEADER`/`_BONE_ANI`/`_VERTEX_ANI` 等在引擎 `KG3D_Animation.h`/相关头;复刻 `Ani.h` 自维护副本,按字节对齐。

对标源总览:
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层 | `KG3D_Animation::LoadFromFile`(`KG3D_Animation.cpp:1277`) | `Ani::ReadFile`(`Ani.cpp:27`) |
| 类型分派 | `switch(m_emAniType)`(BONE_RTS/VERTICES/BINDPOSE_UPDATE 等) | `switch(m_dwType)`(BONE_RTS/VERTICES/default) |
| mask 分派 | `pHead->dwMask`(MASK/MASK_EF/VERVION2_EF/...) | `m_pHead->dwMask`(同) |
| 枚举 | `KG3D_Animation.h` `KG3D_ANIMATION_TYPE` | `Ani.h` `KG3D_ANIMATION_TYPE` 副本 |

---

## 2. 差异比对法（每轮第一步）

引擎 `LoadFromFile` 读 `_ANI_FILE_HEADER` → 按 `dwType`(`KG3D_ANIMATION_TYPE`)分派 → 再按 `dwMask`(`ANI_FILE_MASK_*`)分派读不同结构。复刻 `Ani::ReadFile` 同构(读 header → `switch(m_dwType)` → `switch(m_pHead->dwMask)`)。差异从**类型层 + mask 层 + 结构层**查。

⚠️ **关键**:复刻只需抽 5 个成员(§3),都从头部结构取,**不需要读后续骨骼/顶点数据**(引擎读 RTS/骨骼名等海量数据,复刻不读——这是有意的,不算落后)。所以比对重点是"**头部结构定义 + 类型/mask 分派是否覆盖**",不是逐字节读全部。

### 2.1 类型层(`KG3D_ANIMATION_TYPE`)
- 引擎枚举全集:从 `KG3D_Animation.h` 取所有 `ANIMATION_*`。
- 复刻 `Ani.h` 副本:取所有 `ANIMATION_*`。逐项核对值是否一致(枚举值写进文件,错位会读错类型)。
- 复刻 `switch(m_dwType)` 只 case `ANIMATION_BONE_RTS`/`ANIMATION_VERTICES`,其余落 `default`(打印 unsupport,**不致命**)。
- ⚠️ **潜在落后点(待核实)**:`ANIMATION_BONE_RTS_BINDPOSE_UPDATE`——引擎 `LoadFromFile` 把它**归到 BONE_RTS 处理**(`if (m_emAniType == ANIMATION_BONE_RTS_BINDPOSE_UPDATE) { m_emAniType = ANIMATION_BONE_RTS; }`),但复刻 `Ani.h` 副本可能**没这个枚举值**,且 switch 用 `==ANIMATION_BONE_RTS` 精确匹配 → 该类型落 default 不抽 numBones。**先核实**:该类型是否真写进 `.ani`(grep 引擎 `SaveToFile`/编辑器是否产出此类型);真有才同步(给复刻补枚举值 + switch 归到 BONE_RTS,同引擎)。当前无害则只标注。

### 2.2 mask 层(`ANI_FILE_MASK_*`)
- 引擎/复刻 mask 常量:`ANI_FILE_MASK`/`ANI_FILE_MASK_EF`/`ANI_FILE_MASK_VERVION2_EF`/`ANI_FILE_MASK_VERVION3`/`ANI_FILE_MASK_VERVION2`/`ANI_FILE_MASK_COMPRESS` 等。
- 复刻每个类型(BONE_RTS/VERTICES)的 `switch(dwMask)` 覆盖 `MASK`/`MASK_EF`/`VERVION2_EF`,`default` 读 VERSION2 结构。
- 差异:引擎新增 mask(新版本格式)→ 复刻补 case + 对应结构,且 `GetAniMaskTypeMap()` 补该 mask+描述(见 §3 `m_dwMask` 抽取要点的三处都补)。`ANI_FILE_MASK_VERVION3`(Rust Clip,0x4D494E41)**已对齐**:复刻用 `clip::Clip`(现成 Rust 库)解析抽 `m_dwNumBones`,不再直接退出(详见 §4 构建/VERVION3 说明)。
</br>
> **VERVION3(Rust clip)解析说明**:引擎 `KG3D_Animation::LoadFromFile:1548` 用 `clip::Clip`→`Import(buf,len)`→`GetBoneCount()` 抽骨骼数。复刻 `Ani.cpp` 同样用 `clip::Clip`(基类 `m_pbyBuffer` 整文件 buffer 作 Import 入参),`m_bKeyFrame` 保持 false;`BoneCnt==0`(资源异常)由解析时 `OnErrorByGBK(ErrorLevel::ERROR_LEVEL_TOOL_ERR, ErrorType::ERROR_TYPE_RES_READ_EXCEPT, ...)` 报(不是 diff 判;Import 失败也用此报)。**构建依赖**:复刻工程链 `ClipLibX64.lib`+`KESMBaseX64.lib`(import lib,头在 `$JX3ENGINE_Sword3%\Source\Common\RUST\ClipLib` 与 `KESMBase`),运行时依赖 `ClipLibX64.dll`/`KESMBaseX64.dll`——已由 vcxproj `PostBuildEvent` 用环境变量自动拷到 `$(OutDir)`,换机器/重编译不漏。

### 2.3 结构层
- 引擎 `_ANI_FILE_HEADER`/`_BONE_ANI`/`_BONE_ANI_EF`/`_BONE_ANI_VERSION2`/`_BONE_ANI_VERSION2_EF`/`_VERTEX_ANI`/`_VERTEX_ANI_EF`/`_VERTEX_ANI_VERSION2`/`_VERTEX_ANI_VERSION2_EF` 等。
- 复刻 `Ani.h` 副本逐个按字段/大小对齐。新增字段(常带新 mask/版本)→ 复刻结构同步,否则 `dwNumBones`/`dwNumAnimatedVertices` 读错位。

> 实操:grep 各取两侧 `ANIMATION_*`/`ANI_FILE_MASK_*`/`_BONE_ANI*`/`_VERTEX_ANI*` 做集合差 + 结构字段对比,逐项按 2.1/2.2/2.3 核实。结论写进当轮记录。

---

## 3. 抽取信息（同步时的不变量，必须守）

Ani 只抽 **5 个成员**(不是 Pss 的三类,无音频、无明文路径):
| 成员 | 含义 | 来源 | 落库 |
|---|---|---|---|
| `m_dwType` | 动画类型(`ANIMATION_BONE_RTS`/`ANIMATION_VERTICES`/...) | `_ANI_FILE_HEADER.dwType` | 决定 IsBone/IsVertex,不入 Ani 表 |
| `m_dwNumBones` | 骨骼动画的骨骼数(骨骼动画>0,否则0) | `_BONE_ANI*.dwNumBones`(BONE_RTS 分支) | Ani 表 `BoneCnt` |
| `m_dwNumAnimatedVertices` | 顶点动画的顶点数(顶点动画>0,否则0) | `_VERTEX_ANI*.dwNumAnimatedVertices`(VERTICES 分支) | Ani 表 `VertexCnt` |
| `m_bKeyFrame` | 是否抽帧 ani | mask 是 `*_EF` 时置 true | 不入库,用于检查逻辑(KResChecker) |
| `m_dwMask` | Ani 文件版本 mask(`ANI_FILE_MASK`/`_VERVION2`/`_EF`/`_VERVION3` 等) | `_ANI_FILE_HEADER.dwMask`(`Ani.cpp` `m_dwMask = m_pHead->dwMask`) | Ani 表 `dwMask` 列(`InsertAniResult` 第4列,`insert into Ani (FilePath,BoneCnt,VertexCnt,dwMask)`);另 `AniMask` 表存 mask 值→中文描述映射(由 `GetAniMaskTypeMap()` 填) |

**`m_dwMask` 抽取要点**:
- `Ani::ReadFile` 开头 `m_dwMask = m_pHead->dwMask` 取文件版本 mask,**在类型/mask 分派之前**(所有分支共用,必须先取)。
- mask 值→描述映射在 `Ani::GetAniMaskTypeMap()`(静态,列 7 个 `ANI_FILE_MASK_*` 常量及描述),经 `KBase::GetAniMaskTypeMap()` 暴露给报告层,落 `AniMask` 表(`dwMask,Msg`)。
- 同步新增 mask(引擎新版本格式)时:**①** `Ani.h` 加 `ANI_FILE_MASK_*` 常量;**②** `GetAniMaskTypeMap()` 里 `emplace_back` 补该 mask+描述;**③** `ReadFile` 的 mask 分派(`switch(m_pHead->dwMask)`)补 case。三处都补,否则新 mask 的 ani 落 default、AniMask 表缺映射。

**同步任何新类型/mask/结构时,确保对应分支仍正确抽这 5 个**(尤其 `dwNumBones`/`dwNumAnimatedVertices` 从正确结构的正确字段取、`m_dwMask` 在分派前先取)。这是 Ani 技能的"不变量"——同步不该改变现有 ani 的 BoneCnt/VertexCnt/Mask。

---

## 4. 构建（同 Pss）

编译整个解决方案产出扫描器(`Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- **前置:先编译 RUST 依赖工程(同 Pss §4,稳妥起见;对 Ani 尤其重要)**:`Jx3ResFileReaderAPI.vcxproj` link 依赖 `ClipLibX64.lib`/`KESMBaseX64.lib`(import lib),但 `FileParse.sln` 不含这两个工程、不会自动先编。Ani 的 VERVION3(Rust clip)解析直接用 `clip::Clip`(来自 ClipLib),lib 缺失/过期/换机器未编 → 链接 LNK1104 / 运行时 dll 加载失败。每轮先编:
  ```bash
  # bash 下 / 写成 //;dos/cmd 写 /p:
  "$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
  "$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
  ```
- MSBuild:用 `%MSBuildTool%`(见 §1)。命令(在仓库根,用相对 `FileParse.sln`):
  ```bash
  "$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
  ```
  - bash 下 MSBuild 的 `/` 参数写成 `//`。
- **不要用 `Build.cmd`**(带 svn up/git 推送/PE 核验副作用)。本闭环只要 `FileParse.sln` rebuild 出新 exe。
- 判定:退出码 0 且 `x64\Release\Jx3SvnHookCheckTool.exe` 更新时间刷新即成功。编译失败 → 看 MSBuild stdout 先修编译错。

---

## 5. 测试（全量）

用户已定**每轮全量**。全量 = 扫 `$JX3_HD_Client` 下所有 `.ani`(本机约 **23 万**个,实测约 **47 秒/轮**)。

### 5.1 生成扫描清单(GBK!)
`ScanFileList_ani.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 写**(UTF‑8 破坏中文)。用脚本(与 Pss 共享的通用脚本):
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
python ".claude/skills/Ani代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client" \
  --ext  ani \
  --out   "$REPO/x64/Release/logs/ScanFileList_ani.txt"
```
(ani 用独立清单 `ScanFileList_ani.txt`,避免与 Pss 的 `ScanFileList.txt` 互相覆盖。`--root "$JX3_HD_Client"` 深扫整个 client 下 .ani。)

### 5.2 跑扫描器(关键:ReadFileListFromSvnDB=1)
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
# ⚠️ REPO 必须从仓库根(KResourceReader)取,勿在 x64/Release 里用 cd .. && pwd -W 取——cd .. 只退到 x64 一级,pwd -W 得到 仓库根/x64(多了一个 x64 段,即多一层),再拼 $REPO/x64/Release/logs/ScanFileList*.txt 就成了 仓库根/x64/x64/Release/logs/ScanFileList*.txt(x64 重复、文件不存在)→KResScanMgr::MainScan GetLastError(3) 扫0文件、45ms 退出。cwd 在仓库根时 pwd -W 直接对,无需 cd。
cd "$REPO/x64/Release"
# svn wc.db:client 上级是副本根→../.svn,自身是副本根→.svn,两者必须存在一个(§1 前置已查,此为兜底)
WCDB="$JX3_HD_Client/../.svn/wc.db"
if [ ! -f "$WCDB" ]; then WCDB="$JX3_HD_Client/.svn/wc.db"; fi
if [ ! -f "$WCDB" ]; then echo "异常:svn wc.db 不存在,技能终止"; exit 1; fi
ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 \
  ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_ani.txt"
```
- `ReadFileListFromSvnDB=1` → 走 `CopyDataFromWCDBList`:清单(ScanFileListInput)INNER JOIN svn wc.db 取清单文件的元信息(changed_revision/date/author)填 FileList,再 `ProcessMultiThreadMain` 解析——**仍扫清单全量**(不漏文件),只是 FileList 多带 svn 元信息、多~8s 查 svn db。
- **Ani 调用路径**(与 Pss 不同):`Jx3SvnHookCheckTool.exe` → `KResChecker` 遇 `.ani` → `Jx3ResFileReaderLoader::m_pIBase->GetAniInfo` → `KBase::GetAniInfo`(`KBase.cpp`)→ `kg_ani::Ani p; p.ScanFile(pszFile)` → `Ani::ReadFile` → 抽 4 成员 → `InsertAniResult` 进 Ani 表。**不经 reader 工厂 `AddFileType`**(那 30 多注册不含 "ani")——Ani 是经 `GetAniInfo` 这条专用路径调用的。

### 5.3 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下最新时间戳子目录。`ls -t logs/JX3/trunk/ | head -1`。
- `Scan.log`:末尾应类似 `... INFO 日志正常关闭`。
- `ScanResult.db`(Ani 技能关注这两表):
  - **`Ani`**:每行一个解析成功的 ani,字段 `FilePath,BoneCnt,VertexCnt`(+ 新版 exe 加 `dwMask` 列;=§3 的 m_dwNumBones/m_dwNumAnimatedVertices/m_dwMask)。本机约 23 万行。另有 `AniMask` 表(`dwMask,Msg`)存 mask 值→中文描述映射。
  - **`Result`**:`ErrLevel=7` 且 `File` 以 `.ani` 结尾(或 `ExtName=ani`)= 解析失败。Ani 落后多表现为漏抽(Ani 表字段错)而非失败。
  - 关联视图:`ResultAni`/`ResultAniBoneOver`/`ResultAniVertexOver`(骨骼/顶点数超标告警)。

### 5.4 音频标签扫描
**无**。Ani 没有音频标签(文档明确),不跑 `KSearchResource.exe SearchAudioLabel`,不产生 AudioLabel.db。

---

## 6. 差异对比（闭环的"看变化"）

`diff_ani.py` 是**纯差异工具**:只列修改前后数据差异,**不判断差异算回归还是改善**(好坏由报告/Claude 人工裁定)。资源对错(如 VERVION3 `BoneCnt==0`)是 `Ani.cpp` 解析时 `OnErrorByGBK(ERROR_LEVEL_TOOL_ERR, ...)` 报异常的职责,不是 diff 的职责。

每轮:改码前跑一次全量当 baseline,改+编译后跑一次当 current,对比两份 `ScanResult.db`:
```bash
python ".claude/skills/Ani代码同步/scripts/diff_ani.py" "<baseline.db>" "<current.db>" --knownbad "<清单,可选>"
```
脚本输出(纯差异,中性):
- **changed**:两侧都在 `Ani` 表,但 `BoneCnt`/`VertexCnt`/`dwMask` 变了(不判好坏)。如本次 VERVION3 的 BoneCnt 0→40(修复漏抽)会全列在此。
- **appeared**:current 新进 `Ani` 表(baseline 不在:曾失败/未扫到)——如修复漏抽。
- **disappeared**:baseline 在 `Ani` 表、current 不在了(现在失败/未扫到)——**需关注**(可能是回归)。
- **still_failing**:两侧都失败(`ErrLevel=7` .ani)。与 `--knownbad` 交集 = 预期坏文件;其余待人工裁定。
- **new_fail**:baseline 没扫到、current 却失败(同清单下一般不出现,出现即异常)。
- **stable**:两侧都在 `Ani` 表且字段完全相同。
- (dwMask 仅当两侧 db 都有 `dwMask` 列时才参与比较;旧 exe 的 db 无该列则只比 BoneCnt/VertexCnt)
- exit code:0=正常(差异已列);1=异常(`new_fail` 非空);2=输入异常。**差异本身不导致 exit1**。

**如何裁定差异**:
- `changed`/`appeared` 里属于**本轮目标**(如本次 VERVION3)= 预期改善,通过。
- `changed` 里属于**不该碰的类型**(如骨骼动画 BoneCnt 莫名变了)= 回归,回滚重来。
- `disappeared`/`new_fail` = 需关注,逐个排查。
- 资源异常(VERVION3 `BoneCnt==0`)由 Ani.cpp 已 `OnErrorByGBK(ERROR_LEVEL_TOOL_ERR, ...)` 报出,在 `Result` 表里看,不在 diff 判。

**整个闭环终止** = §2 差异比对无待同步项 且 diff 列出的差异全部裁定为"预期"(无意外 `disappeared`/`new_fail`/非目标 `changed`) 且 无 `still_failing` 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经核实(打开文件看是否截断/损坏)后记进 `--knownbad`。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查(6 项:4 环境变量+MSBuildTool+wc.db),任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成全量 ani 清单 → 跑扫描器(§5.2)得 baseline ScanResult.db → 存路径
          (Ani 无音频,不跑 SearchAudioLabel)
B. 比对:  按 §2 三层(类型/mask/结构)比对复刻↔引擎,列当轮待同步项
          (注意 BINDPOSE_UPDATE 等先核实是否真序列化进 .ani,像 Pss 的 UIBOUND)
C. 改码:  改 Ani.cpp/Ani.h(UTF-8,Edit/Write 安全)同步该类型/mask/结构;
          同步时核 §3 五成员是否仍正确抽取
D. 编译:  §4 先编 RUST 依赖(KESMBase/ClipLib,§4 前置,Ani 的 VERVION3 依赖 ClipLib)→ 再 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C
E. 测试:  用 baseline 同一份清单 → 跑扫描器 → current ScanResult.db
F. 判据:  diff_ani.py baseline vs current
          - regressed 非空 → 回滚本轮改动,回到 B
          - 目标 improved 且无回归 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 无回归 且 无非 known-bad 新失败 → 完成
          写报告 UpdateCodeAni.md(§9),再汇报
```

> **只有真正改了代码才写报告**(§9)。四层已对齐、没改码(如纯健康基线检查),不写报告。

护栏(同 Pss):
- **迭代上限:最多 8 轮**。8 轮仍未清零或反复回归,停止并汇报。
- **编译错优先**:编译不过绝不进测试。
- **回滚要干净**:regressed 时把 `Ani.cpp`/`Ani.h` 恢复到本轮改前状态(改前 `cp` 备份到临时目录最稳)。
- **编码**:源码 UTF-8 可 Edit/Write;`ScanFileList_ani.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **全量是默认**:~23 万文件/轮,实测 ~47 秒。子集(`--subset`)只用于迭代试错,终止判据仍以全量无回归为准。
- **五成员**:每轮同步后核 §3 五成员是否补齐(type/numBones/numAnimatedVertices/bKeyFrame/mask)——这是"假成功"主要来源(ani 无音频、无路径,只这 5 个)。
- **不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户，同 Pss）

1. 同步了哪些类型/mask/结构(逐项:引擎文件:行 → 复刻文件:行,补了什么)。
2. 编译状态 + 测试范围(全量 23 万,耗时)。
3. 回归判据:baseline vs current 的 `regressed/improved/still_failing` 计数;known-bad 清单。
4. 终止结论:差异是否清零、是否无回归;撞上限则说明卡在哪轮/哪个类型。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后。

---

## 9. 对比测试报告（落盘 UpdateCodeAni.md）

按 `CodeReviewAni.md` §6 要求,真正改了代码后,闭环收尾把报告写到:
`项目路径\x64\Release\logs\UpdateCodeAni.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(文档要求,重点是 `Result`+`Ani` 表,音频过滤掉):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`。
2. **ScanResult.db 逐表对比**:表 `FileList`/`Result`/`Ani` 等内容——相同、不同,及不同原因(照 Pss 的全表对比,但**无 AudioLabel.db**,不跑音频扫描)。

### 9.1 报告生成方式(脚本 + Claude 分工,同 Pss)
机械对比由脚本做,Claude 补脚本给不出的部分:
```bash
REPO="$(pwd -W)"
python ".claude/skills/Ani代码同步/scripts/gen_report_ani.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "$REPO/x64/Release/logs/UpdateCodeAni.md"
```
- 脚本逐表对比 ScanResult.db 表(FileList/Result/Ani 等)+ 检查 Scan.log,输出 md 片段(UTF‑8)。
- 脚本只给数字和样本,**"代码改动说明"和"不同原因"由 Claude 据本次改动补写**在脚本片段之上。
- **无 `--audiolabel`**(Ani 无音频)。

### 9.2 UpdateCodeAni.md 结构(参考 Pss 的 UpdateCodePss.md 范式)
```
# Ani 代码修改前后对比测试报告
> 生成日期 / 对比 baseline vs current / 全量 23 万 ani

## 一、本次代码改动            ← Claude 写(引擎文件:行 → 复刻文件:行)
## 二、前后对比结果             ← gen_report_ani.py 脚本片段(Scan.log + ScanResult 各表)
## 三、不同原因分析             ← Claude 写
## 四、终止结论                 ← Claude 写
```
- "二"由脚本 `>>` 追加;"一/三/四"由 Claude 写在片段上下。
- 报告 UTF‑8(用 Write/Edit),**不是 GBK**——中文要正常显示。

---

## 附:快速命令速查

```bash
# 仓库根:Claude 执行技能时 cwd 本就在仓库根,pwd -W 直接取到。
# ⚠️ 勿在 x64/Release 里用 cd .. && pwd -W 取 REPO(cd .. 只退到 x64 一级→REPO=仓库根/x64,多了一个 x64 段→拼 $REPO/x64/Release/logs/ScanFileList*.txt 成 仓库根/x64/x64/Release/logs/ScanFileList*.txt,x64 重复、文件不存在→MainScan GetLastError(3) 扫0文件);从仓库根 pwd -W 直接取。
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
cd "$REPO"

# 生成全量 GBK ani 清单
python ".claude/skills/Ani代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client" --ext ani \
  --out   "x64/Release/logs/ScanFileList_ani.txt"

# 编译(先编 RUST 依赖 KESMBase/ClipLib,再编 FileParse.sln;FileParse.sln 不含这两个工程)
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" \
  FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal

# 全量扫描(ReadFileListFromSvnDB=1;清单 JOIN svn db 取元信息,仍扫清单全量;无音频扫描)
cd "x64/Release"
WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"
[ -f "$WCDB" ] || { echo "异常:svn wc.db 两个候选都不存在,技能终止"; exit 1; }
ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_ani.txt"

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1

# 回归对比(Ani 表 + 失败集,无音频)
python ".claude/skills/Ani代码同步/scripts/diff_ani.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>"

# 生成对比报告片段(ScanResult 各表 + Scan.log,无 AudioLabel)
python ".claude/skills/Ani代码同步/scripts/gen_report_ani.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodeAni.md"
```
