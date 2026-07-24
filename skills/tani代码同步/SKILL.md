---
name: tani代码同步
description: 把 Tani 复刻解析器(Tani::ReadFile)与引擎原函数(KG3D_AnimationTani_Data::LoadFromFile)对齐,修复"复刻落后引擎"导致的 .tani(动作动画标签)解析失败/漏抽依赖路径/漏抽音频标签。当用户提到 tani 解析失败、动作动画标签解析失败、Tani 复刻落后引擎、KG3D_AnimationTani_Data/ANIMTAG_* 对齐、SFX/Sound/Motion/CameraAni/Texture/ForceField 新标签类型未同步、tani 漏抽依赖路径或音频、或想让 KResourceReader 正确解析新类型 .tani 时,务必使用本技能。它会自动比对两侧差异、改复刻代码、编译、跑全量测试、前后对比,循环到差异清零且无意外差异为止。
---

# Tani 代码同步（复刻 ↔ 引擎对齐闭环）

## 为什么有这个技能

`KResourceReader` 里的 `Tani::ReadFile`(`kg_tani::Tani`)是引擎 `KG3D_AnimationTani_Data::LoadFromFile` 的**复刻**,解析 `.tani` 动作动画标签文件。`.tani` 把一个 `.ani` 上挂的多种标签(特效 SFX / 声音 Sound / 动作 Motion / 镜头动画 CameraAni / 贴图 Texture / 力场 ForceField)按 `ANI_TAG_BLOCK_HEADER` 分块串行写盘。复刻只"读得动 + 抽资源检查需要的依赖路径/音频标签",不跑标签逻辑。

引擎会持续新增/改标签类型(`KG3D_ANIMTAG_TYPE`/`ANIMTAG_*`)、各标签的版本分支(`dwVersion` 的 `case`/`>= N`)、结构体(`SFX_BIND_BLOCK_FILE_DATA`/`SoundDataSave*`/`MotionTagDataInfoNew` 等)。复刻一旦没跟上,遇到新类型/新版本的 `.tani` 就会**解析失败**或**漏抽依赖/音频**——典型如某标签 `dwVersion` 升了一档加了字段,复刻 `switch` 只到旧 case,后续块错位。

⚠️ **与 Pss 相同、与 kmsc 一致的点**:`Tani` 经 reader 工厂 `AddFileType("tani", ProcessTani)` 调用(**同 kmsc**,不是 Ani 的 `GetAniInfo` 专用路径);抽取信息只有**两类**(明文依赖路径 + 音频标签),**没有 PssInfo 那样的数值汇总**(无包围盒/粒子数等——别找第三类)。`ReadFile` 的 `default` 是 `KG_PROCESS_ERROR(false)` **硬失败**(顶层 tag 分派缺 case 时整个 .tani 解析失败,不是静默漏抽)。

⚠️ **与 Pss/kmsc 的关键差异(比对口径)**:复刻 `HeaderTani.h` **自维护** `KG3D_ANIMTAG_TYPE` 枚举 + 全部结构体(非 `#include` 引擎头,同 Ani 的 `Ani.h`)——落后风险在**枚举值/结构体大小/各函数 switch case**,不在 include 同步。复刻大量用 `SkipData` 跳过它**不需要**的运行时字段(只抽路径+音频),把这些字段折叠进一个大的 `SkipData(DWORD*N)`;引擎逐字段 `CopyData` 读取并按内部 `uVersion` 设默认值。**比对的核心是"每段字节总数对齐 + 版本分支 case 覆盖"**,不是逐字段读取方式——复刻一段 `SkipData(BOOL)+SkipData(int)+SkipData(DWORD*26)` 与引擎 `CopyData(BOOL)+CopyData(int)+...+Seek(DWORD*25)` 只要**总字节数相等**即对齐(详见 §2.2)。

本技能把"对齐复刻与引擎"做成**全自动闭环**(同 Pss/kmsc):比对差异 → 改复刻代码 → 编译 → 跑全量测试 → 前后对比 → 有意外差异就回滚,直到差异清零。过程中**守住两类信息抽取口径**(路径 + 音频)。

> 工作模式:**全自动闭环**(同 Pss/kmsc),中途不必征询用户,收尾汇报。护栏见 §7。仅在 windows 下执行。

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
> - 任一**必需**项缺失 → 报错并停止。

> **项目路径(仓库根)**(同 Pss):`KResourceReader` 仓库根 = 本 SKILL.md 上溯 4 级 = Claude 执行技能时的工作目录(Primary working directory)。说明路径写作 `项目路径\...`;bash 命令块用 `REPO="$(pwd -W)"`(Windows 绝对,exe 能接受),块内 `$REPO/...`;传 exe 的文件路径必须绝对(exe 内部 `SetCurrentDirectoryA` 到 client,相对路径失效)。Claude 执行技能 cwd 本就在仓库根,`pwd -W` 直接对。

复刻侧（你要改的，UTF‑8，Edit/Write 安全）:
- **复刻工程**:`项目路径\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj`(`Tani.cpp` 编进此工程,以 `..\src\Tani\Tani.cpp` 引用;编译 `FileParse.sln` 时随此工程出 `Jx3ResFileReaderAPI.dll`)
- `项目路径\src\Tani\Tani.cpp`（顶层 `ReadFile` + 各标签函数 `SFX`/`Sound`/`Motion`/`KG3D_AnimationCameraAniTag_Group_Data`/`KG3D_AnimationTextureTag_Group_Data`/`KG3D_AnimationForceFieldTag_Group_Data`）
- `项目路径\src\Tani\HeaderTani.h`（**自维护** `ANI_TAG_FILE_HEADER`/`ANI_TAG_BLOCK_HEADER`/`KG3D_ANIMTAG_TYPE` 枚举/各标签结构体 `SFX_BIND_BLOCK_FILE_DATA`/`SoundDataSave*`/`MotionTagDataInfoNew`/`CameraAniDataSave`/`FORCE_FIELD_BIND_BLOCK_FILE_DATA` 等,非 include 引擎——落后风险在结构/枚举值与各函数 switch case,不在 include 同步,同 Ani 的 `Ani.h`）
- `项目路径\src\Tani\Tani.h`（`Tani` 类 + `sTaniData m_sData`）
- 若上面不存在,从本 SKILL.md 目录上溯 4 级再下 `src\Tani`:`%cd%\..\..\..\..\src\Tani\Tani.cpp`(`%cd%` 指本 SKILL.md 目录,非 CodeReviewTani.md 目录)。

引擎侧（对标口径,**只读不改**;路径用环境变量 `%JX3ENGINE_Sword3%`,本机 = `D:\JX3\trunk\Sword3`）:
- **引擎原函数工程**:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Module\KG3D_AnimationTag\KG3D_AnimationTag_2019.vcxproj`(`KG3D_AnimationTani_Data.cpp` 等在此工程;只读对标,不编不建)
- 顶层原函数:`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Module\KG3D_AnimationTag\KG3D_AnimationTani_Data.cpp` 的 `KG3D_AnimationTani_Data::LoadFromFile`（读 `ANI_TAG_FILE_HEADER` → 校验 mask/version → 循环 `dwNumBlock` 读 `ANI_TAG_BLOCK_HEADER` → `_NewTagData(eTagType)` 建对应 `Group_Data` → `Group_Data::LoadFromFile(piBuffer, dwVersion, dwNumKeyFrames)`）
- **标签类型枚举(口径来源)**:`KG3D_ANIMTAG_TYPE`(`ANIMTAG_SFX`/`ANIMTAG_SOUND`/`ANIMTAG_MOTION`/`ANIMTAG_CAMERA_ANI`/`ANIMTAG_TEXTURE`/`ANIMTAG_FORCE_FIELD`/`ANIMTAG_COUNT`)在 `%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\InternalPublish\Include\AnimationTag\IKG3D_AnimationTag.h`。⚠️ 该文件在 `InternalPublish\Include\AnimationTag\` 下,**不在** `...\Module\KG3D_AnimationTag\` 下,别取错。复刻 `HeaderTani.h` 有 `enum class` 副本,逐项核对值一致(枚举值写进文件,错位会读错标签类型)。
- **per‑type 标签读取(逐类型同步的真正落点)**:`...\Internal\Module\KG3D_AnimationTag\KG3D_Animation{SFX,Sound,Motion,CameraAniTag,Texture,ForceField}Tag_Group_Data.cpp` 各 `LoadFromFile(IKG3D_BufferReader*, DWORD dwVersion, DWORD dwNumKeyFrames)`,及对应 `_Group_Data.h` 的结构体。**各标签自己的 `dwVersion` 分支都在这里**(§2.2)。
- **结构体口径**:`...\KG3D_AnimationTani_Data.h`(`ANI_TAG_FILE_HEADER`/`ANI_TAG_BLOCK_HEADER`)+ 各 `_Group_Data.h`(标签结构)。复刻 `HeaderTani.h` 自维护副本,按字节对齐。
- **读写基准**:`...\KG3D_AnimationTani_Data.cpp` 的 `SaveToFile` + 各 `Group_Data::SaveToFile`(writer 与 reader 字节数逐一吻合的基准,反推 reader 字节数)。
- 抽取信息结构:`项目路径\include\IJx3ResFileReader.h`(tani 无类似 `PssInfo` 的汇总结构——只有 `sTaniData`(vPssFile/vFrameInfo)内部用,不入库,见 §3)。

对标源总览:
| 层级 | 引擎文件 | 复刻对应 |
|---|---|---|
| 顶层遍历 | `KG3D_AnimationTani_Data::LoadFromFile`(`KG3D_AnimationTani_Data.cpp:109`) | `Tani::ReadFile`(`Tani.cpp:369`) |
| 标签块分派 | `_NewTagData(eTagType)` switch(`KG3D_AnimationTani_Data.cpp:322`) | `switch(pAniTagBlockHeader->eTagType)`(`Tani.cpp:397`) |
| SFX 标签 | `KG3D_AnimationSFXTag_Group_Data::LoadFromFile` | `Tani::SFX`(`Tani.cpp:22`) |
| Sound 标签 | `KG3D_AnimationSoundTag_Group_Data::LoadFromFile` | `Tani::Sound`/`SoundSoundDataSaveVersion2`(`Tani.cpp:151`/`86`) |
| Motion 标签 | `KG3D_AnimationMotionTag_Group_Data::LoadFromFile` | `Tani::Motion`(`Tani.cpp:253`) |
| CameraAni 标签 | `KG3D_AnimationCameraAniTag_Group_Data::LoadFromFile` | `Tani::KG3D_AnimationCameraAniTag_Group_Data`(`Tani.cpp:307`) |
| Texture 标签 | `KG3D_AnimationTextureTag_Group_Data::LoadFromFile` | `Tani::KG3D_AnimationTextureTag_Group_Data`(`Tani.cpp:326`) |
| ForceField 标签 | `KG3D_AnimationForceFieldTag_Group_Data::LoadFromFile` | `Tani::KG3D_AnimationForceFieldTag_Group_Data`(`Tani.cpp:342`) |
| 枚举 | `IKG3D_AnimationTag.h` `KG3D_ANIMTAG_TYPE`(C-style `enum`) | `HeaderTani.h` `KG3D_ANIMTAG_TYPE`(`enum class` 副本,自维护) |

> **tani 调用路径(同 kmsc,reader 工厂分派)**:`Jx3SvnHookCheckTool.exe` → `Jx3ResFileReaderAPI`(reader 工厂按扩展名分派)→ `ProcessTani`(`Jx3ResFileReaderAPI.cpp:278`,`return new kg_tani::Tani()`)→ `Tani::ReadFile`。`AddFileType("tani", ...)` 在 `Jx3ResFileReaderAPI.cpp:120`。

---

## 2. 差异比对法（每轮第一步）

引擎 `LoadFromFile` 读 `ANI_TAG_FILE_HEADER`(校验 `dwMask==0x41544147`("ATAG")、`dwVersion==0||1`)→ 注册 `szAnimationFileName` → 循环 `dwNumBlock` 读 `ANI_TAG_BLOCK_HEADER(eTagType, dwVersion, dwNumKeyFrames)`:
- `dwNumKeyFrames==0` 时:若 `eTagType==ANIMTAG_MOTION` 且 `1<=dwVersion<3`,跳 `sizeof(DWORD)*2`(头填充),`continue`;
- 否则 `_NewTagData(eTagType)` 按 `KG3D_ANIMTAG_TYPE` 分派到对应 `Group_Data::LoadFromFile(piBuffer, dwVersion, dwNumKeyFrames)`。

复刻 `Tani::ReadFile` 同构(读 header → 校验 → 注册 `szAnimationFileName` → 循环 block → `dwNumKeyFrames==0` 的 MOTION 特判 → `switch(eTagType)` 分派到 `SFX`/`Sound`/`Motion`/`KG3D_AnimationCameraAniTag_Group_Data`/`KG3D_AnimationTextureTag_Group_Data`/`KG3D_AnimationForceFieldTag_Group_Data`,`default` `KG_PROCESS_ERROR(false)` 硬失败)。

⚠️ **差异重点有三个,缺一不可**:
1. **标签类型层**(`eTagType` switch,§2.1)——新增 `ANIMTAG_*` 标签类型。
2. **per‑type 版本分支层**(§2.2)——**遍布各标签的 `LoadFromFile`,是普遍的落后来源**:每个标签的 `switch(dwVersion)` / `if (dwVersion >= N)` / `if (dwVersion == N)` 分支,**新版本号恒大于老版本号,引擎新版本会在分支里加新字段/新读取**。复刻没跟到新版本号就错位/漏抽。
3. **结构体层**(§2.3)——header/block/标签结构新增字段或改大小,复刻 `HeaderTani.h` 副本没跟则后续字段错位(最隐蔽,不报错但读错)。

⚠️ **比对口径关键:区分"字节布局分支"与"运行时默认分支"**(这是 tani/Pss/kmsc 通用、Ani 亦同的陷阱):
- **字节布局分支**(`dwVersion >= N` / `== N` 决定**读几个字节**):复刻**必须对齐**——分支缺了或字节数不对,后续块全错位。这是 §2.2 的比对重点。
- **运行时默认分支**(读了字段后,按某个内部 `uVersion` 设运行时默认值,如 SFX `if (uVersion < 20230404) bScaleByShape=TRUE;`、CameraAni `if (pDataIn->dwVersion < 2) bUseByTrack=TRUE;`):**不影响字节布局**,复刻只抽路径/音频、不需要这些运行时默认——**复刻正确地用 `SkipData` 把这些字段一起跳过**,不算落后。比对时不要把"复刻没设运行时默认"当差异。
- **判定法**:看该分支是否改变 `Reference`/`CopyData`/`SkipData`/`Seek` 的**字节数**。改变字节数=字节布局分支(要对齐);只改运行时变量值、字节数不变=运行时默认分支(复刻跳过即可)。

### 2.1 标签类型层(`KG3D_ANIMTAG_TYPE` / `eTagType`)
- 枚举全集:从 `IKG3D_AnimationTag.h` 取所有 `ANIMTAG_*`(排除 `ANIMTAG_COUNT` 哨兵)。当前 6 个:`SFX`/`SOUND`/`MOTION`/`CAMERA_ANI`/`TEXTURE`/`FORCE_FIELD`。
- 复刻 `HeaderTani.h` 副本:取所有 `ANIMTAG_*`,逐项核对值一致(枚举值写进文件,错位读错标签)。
- 复刻 `switch(pAniTagBlockHeader->eTagType)`(`Tani.cpp:397`):6 个 case + `default` `KG_PROCESS_ERROR(false)` 硬失败。
- 引擎 `_NewTagData` switch(`KG3D_AnimationTani_Data.cpp:322`):6 个 case + `default`(只 `KG_PrintfLog` 警告,不致命——但缺 case → `piTag_Group_Data=nullptr` → `KGLOG_PROCESS_ERROR` 失败 → 该 .tani 失败)。
- 差集:引擎有、复刻 `switch` 缺的 `ANIMTAG_*` = **候选同步项**。复刻 `default` 硬失败——引擎新增标签类型且写进 `.tani` 时,含该标签的 .tani **直接解析失败**(同 kmsc 的 NewAction 硬失败语义),闭环到时按本节补 case。
- ⚠️ **"switch 缺 case" ≠ "必须同步"**:逐类型核实它**是否真被序列化进 `.tani`**。核实办法:看引擎 `KG3D_AnimationTani_Data::SaveToFile`(`KG3D_AnimationTani_Data.cpp:230`)是否会把该 `eTagType` 的 `Group_Data` 写进文件(`GetTagCount()>0` 才写),以及编辑器是否产出此类型。只对"会被写进 .tani"的类型同步。
- 对每个确认要同步的类型:去引擎对应 `KG3D_AnimationXxxTag_Group_Data::LoadFromFile`,**按字节顺序**把读取序列搬进复刻(在 `Tani.cpp` 加同名函数 + `ReadFile` switch 加 case + `HeaderTani.h` 加枚举值与结构),套用复刻现有风格(`Reference` 直读结构 + `SkipData` 跳过不要的字段 + `OnReadResourceFileByGBK`/`AddWwiseEvent`/`AddFmod` 抽两类信息)。

### 2.2 per‑type 版本分支层(遍布各标签,**重点**)
每个标签的 `Group_Data::LoadFromFile(buffer, dwVersion, dwNumKeyFrames)` 内部按 `dwVersion`(来自 `ANI_TAG_BLOCK_HEADER.dwVersion`)分派。引擎 `SaveToFile` 写盘的当前版本见 `g_currTagDataVersion[ANIMTAG_COUNT] = { 3, 2, 1 }`(`KG3D_AnimationTani_Data.cpp:24`)——即 SFX 当前存 v3、Sound 存 v2、Motion 存 v1、CameraAni/Texture/ForceField 存 v0(数组只初始化前 3,其余 0)。复刻各函数的 `switch(dwVersion)` / `if (dwVersion >= N)` 要覆盖引擎写盘会产出的版本。

逐标签两侧分支上限(行号会随代码变,以当前文件为准):
| 标签 | 引擎分支 | 复刻分支 | 当前对齐 |
|---|---|---|---|
| SFX | `if (dwVersion >= 1)` 读扩展 BOOL/int + `Seek(DWORD*25)`;`if (dwVersion == 3)` 多读 `bPositionOnly` | `Tani::SFX` 同:`if (dwVersion >= 1)` + `if (dwVersion == 3)`,扩展段用 `SkipData(BOOL)/SkipData(int)/SkipData(DWORD*26)` 跳过 | ✅ 字节数对齐(见下"折叠"说明) |
| Sound | `switch`: case 0/1/2/3/4 + default;case 3 跳 8728 字节(废弃);case 4 读 `SoundVersion3Header` + `SoundDataSaveVersion2` × dwNumKeyFrames + 每个 keyframe 读 `pVersion3Header->dwSoundType` 个 `AnimationSoundTagInfo` | `Tani::Sound` 同:case 0/1/2/3/4 + default;case 3 `SkipData(8728)`;case 4 同结构 | ✅ |
| Motion | `switch`: case 0(case 0 转 v1);case 2 读 SFX bind 后**贯穿落 case 1**(无 break,注释 "by llg，有这个就行了吧");case 1 读 start/end frame + `MotionTagDataInfoNew` × dwNumKeyFrames + 每个 keyframe 按存盘的 `dwBlockLength[j]` 读扩展块 | `Tani::Motion` 同:case 0;case 2 读 SFX bind **贯穿落 case 1**(注释 "注释掉被坑一次"——指此贯穿);case 1 `SkipData(sizeof(DWORD)*2)` + `MotionTagDataInfoNew` + `SkipData(dwBlockLength[j])` | ✅ |
| CameraAni | 每 keyframe 读 `CameraAniDataSave`(定长);`if (pDataIn->dwVersion < 2) bUseByTrack=TRUE`(运行时默认,不改字节布局) | `Tani::KG3D_AnimationCameraAniTag_Group_Data` 每 keyframe 读 `CameraAniDataSave` + 注册 `szCameraAniFileName`;不判 `dwVersion<2`(运行时默认,复刻不需要) | ✅ |
| Texture | 每 keyframe 读 `TextureDataSaveVersion1`(定长)+ `AddTextureTag` | `Tani::KG3D_AnimationTextureTag_Group_Data` 同:读 `TextureDataSaveVersion1` + `AddTextureTag`(正常扫描 `m_bWriteTag=false` 即 no-op,见 §3 附注) | ✅ |
| ForceField | 读 `dwBindCount` × `FORCE_FIELD_BIND_BLOCK_FILE_DATA` + `dwNumKeyFrames` × `FORCE_FIELD_KEYFRAME_FILE_DATA`(无版本分支) | `Tani::KG3D_AnimationForceFieldTag_Group_Data` 同 | ✅ |
| 文件头 | `dwMask==s_dwMask`、`dwVersion==s_dwVersion0(0)\|\|s_dwVersion1(1)`;`SaveToFile` 写 v1 | `Tani::ReadFile` 同校验(`Tani.cpp:378`) | ✅(引擎若加 `s_dwVersion2` 需同步) |

> **"折叠"对齐说明(以 SFX 为例,务必理解)**:引擎 `if (dwVersion >= 1)` 段逐字段读 `bScaleByShape(BOOL)`+`uVersion(int)`+`bProhibitScale(BOOL)`+`bDisableInMobile(BOOL)`+`bFollowTargetAtOrigin(BOOL)`+`nShowType(int)`+`bCustomScale(BOOL)` + `Seek(DWORD*25)` = 7×4 + 100 = 128 字节,之后按 `uVersion` 设运行时默认。复刻 `if (dwVersion >= 1)` 段 `SkipData(BOOL)`+`SkipData(int)`+`SkipData(BOOL)`+`SkipData(BOOL)`+`SkipData(BOOL)`+`SkipData(int)` + `SkipData(DWORD*26)` = 6×4 + 104 = 128 字节——复刻把引擎第 7 个 `BOOL(bCustomScale)` **折叠进** `DWORD*26`(4+25×4=104),**总字节数与引擎相等(128)**,版本分支(`>=1`/`==3`)也一致,故对齐。复刻跳过 `uVersion` 运行时默认逻辑(只抽路径/音频,不需要)——这是**有意的**,不算落后。同步新版本分支时,照此法:**保证每段 `Reference`/`SkipData` 的总字节数与引擎该版本一致**,不追求逐字段读取方式相同。

> 实操:grep 各取两侧 `ANIMTAG_*` 做 case 集合差(§2.1),对每个标签 grep `dwVersion >=|dwVersion ==|case [0-9]` 各取两侧分支上限(§2.2),grep 各标签结构体名比字段/大小(§2.3),再人工逐项按 §2.1/§2.2/§2.3 核实(注意 §2 顶部的"字节布局 vs 运行时默认"区分)。结论写进当轮记录(改了哪个标签/补了哪个版本分支/对应引擎文件:行)。

### 2.3 结构体层
- 引擎:`KG3D_AnimationTani_Data.h`(`ANI_TAG_FILE_HEADER`/`ANI_TAG_BLOCK_HEADER`)+ 各 `KG3D_AnimationXxxTag_Group_Data.h`(`SFX_BIND_BLOCK_FILE_DATA`/`SFX_KEYFRAME_FILE_DATA`/`SoundDataSave*`/`MotionTagKeyframeSave`/`MotionTagDataInfoNew`/`CameraAniDataSave`/`TextureDataSaveVersion1`/`FORCE_FIELD_BIND_BLOCK_FILE_DATA`/`FORCE_FIELD_KEYFRAME_FILE_DATA` 等)。
- 复刻:`HeaderTani.h` 的对应结构(**自维护副本**)。
- 差异:引擎结构新增字段/改大小(常带新 `dwVersion` 分支)→ 复刻 `HeaderTani.h` 结构与版本分支都要同步,**否则 `Reference(sizeof(XxxData))` 读的长度错、后续错位**。这类错位最隐蔽(不报错但读错路径/音频位置)。用各 `Group_Data::SaveToFile`/`KG3D_AnimationTani_Data::SaveToFile` 反推 writer 字节数,与复刻 reader 逐一核对。

---

## 3. 两类信息抽取（同步时的不变量，必须守）

⚠️ **tani 没有 PssInfo 那样的数值汇总**(无包围盒/粒子数/材质数等),它只抽**两类**:明文依赖路径 + 音频标签。同步任何新标签类型/版本分支/结构时,这两类**必须跟着补**。**口径以宏为信号,宁多勿漏**:凡是见到 `MAX_PATH`/`FILENAME_MAX` 参与 `OnReadResourceFileByGBK(..., 字段)` 或 `Reference(...,sizeof(XxxData))` 里带 `[MAX_PATH]` 的字段,就可能是外部资源路径,一律登记,不靠字段名过滤。

> 复刻 `Tani::ReadFile` 里 `sTaniData m_sData`(`vPssFile`/`vFrameInfo`)只是 SFX 标签的内部收集,**不入库、不参与前后对比**——别当成"第三类数值汇总"。

### 3.1 明文依赖路径（登记 `OnReadResourceFileByGBK(路径, ...)`）
登记接口 `OnReadResourceFileByGBK`(经 `KReadFileBase`,扫描时落 `ScanResult.db` 的 `Result` 表,`SonFile`/`SonExtName` = 依赖,`File` 以 `.tani` 结尾)。已知登记点(`Tani.cpp` 行号会随代码变,以当前文件为准):
| 来源 | 字段 | 大致行号 | 备注 |
|---|---|---|---|
| 文件头 `Tani::ReadFile` | `szAnimationFileName`(.ani 路径) | ~382 | 每个tani都有,头一个 |
| SFX 标签 `Tani::SFX` | `cszSFXFileName`(bind 的 .sfx/.mesh 等) | ~35 | bind 块循环登记 |
| Motion 标签 `Tani::Motion` case 2 | `cszSFXFileName` | ~276 | case 2 的 bind 块 |
| CameraAni 标签 | `szCameraAniFileName`(.ani 镜头动画) | ~317 | 每 keyframe 登记 |
| ForceField 标签 | `cszForceFieldFileName`(.fga 力场) | ~352 | bind 块循环登记 |
| Sound 标签 case 0/1/2/4 | `strSoundFileName` | ~117/136/163/191 | **仅 `.ogg`/`.wav`/`.mp3` 结尾才登记**(EndWith 判断) |

### 3.2 音频标签（`KGShare::SoundLabel::Instance().AddWwiseEvent` / `AddFmod`）
凡是涉及音效标签的一律捞,不得漏。新增带音频的标签必须补登记。音频落独立的 `AudioLabel.db` 的 `File(File,EventName,AudioFile)` 表(由 `KSearchResource.exe SearchAudioLabel` 全库扫产出,见 §5.3)。
| 来源 | 调用 | 大致行号 | 类型 |
|---|---|---|---|
| Sound 标签(Wwise) `SoundSoundDataSaveVersion2` | `AddWwiseEvent(GetSrcFile(), strEventName)` | ~96 | `strTagName=="Wwise"` |
| Sound 标签(Fmod) case 1/2 | `AddFmod(GetSrcFile(), pszFile)` | ~111/185 | fmod 事件名 |

> **音频标签可前后对比(纳入判据)**:`AddWwiseEvent`/`AddFmod` 落 `AudioLabel.db` 的 `File` 表 `.tani` 部分。改码前后各跑一份 `SearchAudioLabel`、`diff_tani.py --audiolabel` 按 `.tani` 过滤比 `(File,EventName,AudioFile)` 三元组集合,`audio_only_baseline`(baseline 有 current 无)= 漏抽音频(中性,配合人工裁定,见 §6)。
>
> 另:`Sound` 还调 `InsertFmt(...)` 落 `AudioLabel.db` 的 `LogInfo(File,SubFile,Msg)` 表(诊断日志,非音频判据),`gen_report_tani.py` 会逐表对比到(§9)。

> 每轮同步后,逐类型自问:这个新标签/版本的 `MAX_PATH` 读取登记依赖了吗?有音频吗(AddWwiseEvent/AddFmod)?两类都要有结论。**没有第三类(数值汇总)**——别照搬 Pss 的 §3.3。

> **附:Texture 标签的纹理标签(TaniTag)不在本技能范围**。`Tani::KG3D_AnimationTextureTag_Group_Data` 调 `KGShare::TaniTag::Instance().AddTextureTag(...)`,但 `TaniTag::m_bWriteTag` 默认 `false`,正常 `Jx3SvnHookCheckTool` 扫描时 `AddTextureTag` 早返(`KG_PROCESS_SUCCESS(!m_bWriteTag)`)、**不写库**。纹理标签只在独立命令 `KSearchResource.exe SearchTaniTextureTag`(扫 `data\source` 下 `.tani`,写 `TaniTag` db)才产出——那是另一个工具流程,**本技能不跑、不对比**(spec §3 只列路径+音频两类)。知道它存在即可,别误以为漏抽。

---

## 4. 构建（同 Pss）

编译整个解决方案产出扫描器(`Jx3SvnHookCheckTool.exe` 在 `x64\Release\`):
- `Tani.cpp` 在 `Jx3ResFileReaderAPI.vcxproj`。
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

全量 = 深扫 `$JX3_HD_Client` 下所有 `.tani`(本机约 **5.6 万**个,实测约十几秒/轮——扫描只读头部+按存盘长度跳字节、不 cook、多线程,不慢)。`.tani` 实际都在 `data\source\...` 下,`--root "$JX3_HD_Client"` 深扫可全覆盖。

### 5.1 生成扫描清单(GBK!)
`ScanFileList_tani.txt` 必须 **GBK(cp936)、每行 1 个绝对路径**。**不要用 Edit/Write 写**(UTF‑8 破坏中文)。用脚本(与 Pss/Ani/kmsc 共享的通用脚本):
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
python ".claude/skills/tani代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client" --ext tani \
  --out   "$REPO/x64/Release/logs/ScanFileList_tani.txt"
```
(tani 用独立清单 `ScanFileList_tani.txt`,避免与 Pss/Ani/kmsc 的清单互相覆盖。`--root "$JX3_HD_Client"` 深扫整个 client 下 .tani。)

### 5.2 跑扫描器(关键:ReadFileListFromSvnDB=0)
```bash
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)
# ⚠️ REPO 必须从仓库根(KResourceReader)取,勿在 x64/Release 里用 cd .. && pwd -W 取——cd .. 只退到 x64 一级,pwd -W 得到 仓库根/x64(多了一个 x64 段,即多一层),再拼 $REPO/x64/Release/logs/ScanFileList*.txt 就成了 仓库根/x64/x64/Release/logs/ScanFileList*.txt(x64 重复、文件不存在)→KResScanMgr::MainScan GetLastError(3) 扫0文件、45ms 退出。cwd 在仓库根时 pwd -W 直接对,无需 cd。
cd "$REPO/x64/Release"
# svn wc.db:client 上级是副本根→../.svn,自身是副本根→.svn,两者必须存在一个(§1 前置已查,此为兜底)
WCDB="$JX3_HD_Client/../.svn/wc.db"
if [ ! -f "$WCDB" ]; then WCDB="$JX3_HD_Client/.svn/wc.db"; fi
if [ ! -f "$WCDB" ]; then echo "异常:svn wc.db 不存在,技能终止"; exit 1; fi
ReadFileListFromSvnDB=0 bTest=1 ForDebug=0 \
  ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_tani.txt"
```
- `ReadFileListFromSvnDB=0` → 走 `ScanByFileList` 精确扫清单(=1 查 svn db 改动文件,非全量)。
- `bTest=1` → 测试环境,不上报。
- 工具 `setlocale(LC_ALL, ".936")`,自己处理 GBK,中文路径 OK。
- **tani 调用路径**:见 §1 末尾(reader 工厂 `ProcessTani` → `Tani::ReadFile`)。依赖路径经 `OnReadResourceFileByGBK` 落 `ScanResult.db` 的 `Result` 表。

### 5.3 跑音频标签扫描(改码前后各一次,路径不同!)
音频标签(§3.2 的 AddWwiseEvent/AddFmod)不落 `ScanResult.db`,落独立的 `AudioLabel.db`,由 `KSearchResource.exe SearchAudioLabel` **全库扫**产出(扫 `data\movie .kmsc` + `data\source\other .pss` + `data\source .tani`,不按 ScanFileList,~13 秒,实测)。tani 的音频标签在 `File` 表 `.tani` 部分。
```bash
REPO="$(pwd -W)"
cd "$REPO/x64/Release"
# 改码前(baseline):注意!前后必须不同 db 文件名,否则后跑覆盖先跑、没法对比
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "$REPO/x64/Release/logs/AudioLabel_tani_baseline.db"
# 改码后(current):换文件名
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "$REPO/x64/Release/logs/AudioLabel_tani_current.db"
```
- `argc==4`:`argv[1]=SearchAudioLabel`,`argv[2]=client`(工具自己 `SetCurrentDirectoryA` 到此),`argv[3]=output db`。
- `AudioLabel.db` 表:`File(File,EventName,AudioFile)` 音频标签(tani 取 `.tani` 部分)+ `LogInfo`(InsertFmt 诊断)+ `NewMovieInfo`/`MovieKrlTxt`/`FilterKmsc`(kmsc 协议动画相关,tani 技能只取 `File` 表 `.tani` 部分做判据,其余表 `gen_report_tani.py` 会逐表对比到,见 §9)。
- ⚠️ **前后必须不同 db 文件名**(如上 `_baseline`/`_current`)。`SoundLabel::InitDB` 先 `DeleteFileA` 再建,同路径后跑必覆盖先跑。
- ⚠️ **跑完保留 AudioLabel_tani_*.db,不要删**。这是技能输出文件,留在 `x64\Release\logs\` 供查阅/复算,**禁止 rm 删除**(清理临时只清 ScanFileList 等纯中间产物,AudioLabel db 不算中间产物)。

### 5.4 读报告
- 报告目录:`x64\Release\logs\JX3\trunk\` 下最新时间戳子目录。`ls -t logs/JX3/trunk/ | head -1`。
- `Scan.log`:末尾应类似 `... INFO 日志正常关闭`。
- `ScanResult.db`(**tani 不关注 Pss 表**,看这些):
  - `FileList`:扫到的文件集(应含全部 ~5.6 万 .tani)。
  - `Result`:tani 的两类落库都在这——
    - 解析失败:`ErrLevel=7` 且 `File` 以 `.tani` 结尾(顶层 `default` 硬失败或某标签读错)。
    - 依赖路径:`File` 以 `.tani` 结尾的记录,`SonFile`/`SonExtName` = 抽出的依赖(.sfx/.mesh/.ani/.fga/.ogg/.wav/.mp3 等),`ErrLevel` 多为 3/5。依赖类型见 §3.1 分布。
  - (无 tani 专门"成功"表——不像 Pss 有 `Pss` 表;同 kmsc。)

---

## 6. 差异对比（闭环的"看变化"）

`diff_tani.py` 是**纯差异工具**(同 kmsc/Ani 方案):只列修改前后数据差异,**不判断差异算回归还是改善**(好坏由报告/Claude 人工裁定)。资源对错是 `Tani.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报的职责,不是 diff 的职责。

每轮:改码前跑一次全量(baseline ScanResult.db + baseline AudioLabel.db),改+编译后再跑一次(current),对比:
```bash
python ".claude/skills/tani代码同步/scripts/diff_tani.py" "<baseline ScanResult.db>" "<current ScanResult.db>" \
  --audiolabel "<baseline AudioLabel.db>" "<current AudioLabel.db>" --knownbad "<清单,可选>"
```
脚本输出(纯差异,中性):
- **changed**:两侧都解析成功(都在 `Result` 但非 `ErrLevel=7`),但依赖集变了(中性,不判好坏)。如修复某标签漏抽导致依赖变化会列在此。
- **appeared**:current 新进(baseline 失败/未扫到)——如修复硬失败。
- **disappeared**:baseline 有、current 不在了(需关注,可能回归)。
- **still_failing**:两侧都失败(`ErrLevel=7` .tani)。与 `--knownbad` 交集 = 预期坏文件(截断/损坏);其余待人工裁定。
- **new_fail**:baseline 没扫到、current 却失败(同清单下一般不出现,出现即异常)。
- **stable**:两侧都成功且依赖集完全相同。
- 音频(`--audiolabel`):比 `AudioLabel.db` `File` 表 `.tani` 部分的 `(File,EventName,AudioFile)` 三元组,`audio_only_baseline`/`audio_only_current` 计变化(中性)。
- (diff 比两类:解析失败集 `Result` `ErrLevel=7` .tani + 依赖路径集 `Result` `File=.tani` 的 `SonFile`;`--audiolabel` 比音频标签 `AudioLabel.db` `File` 表 .tani 部分)
- exit code:0=正常(差异已列);1=异常(`new_fail` 非空);2=输入异常。**差异本身不导致 exit1**。

**如何裁定差异**:
- `changed`/`appeared` 里属本轮目标(如修复某标签类型漏抽/硬失败)= 预期改善,通过。
- `changed` 里属不该碰的标签(如 SFX 依赖莫名变了)= 回归,回滚重来。
- `disappeared`/`new_fail` = 需关注,逐个排查。
- 音频 `audio_only_baseline` 里属本轮目标 = 修复漏抽音频;属不该碰的 = 回归。

**整个闭环终止** = §2 差异比对无待同步项 且 diff 列出的差异全部裁定为"预期"(无意外 `disappeared`/`new_fail`/非目标 `changed`/非目标音频丢失) 且 无 `still_failing` 之外的新失败。

`known-bad` 清单:首轮 baseline 的 `still_failing` 经你核实(打开文件看是否截断/损坏,类比 `CodeReviewKMSC` 的 32KB 截断案例)后,记进 `--knownbad`,后续不再当回归。

---

## 7. 全自动闭环流程（按此执行）

```
0. 前置:  按 §1 前置环境检查(6 项:4 环境变量+MSBuildTool+wc.db),任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成全量 tani 清单(--root $JX3_HD_Client --ext tani)→ 跑扫描器(§5.2)得 baseline ScanResult.db
          + 跑 SearchAudioLabel(§5.3)得 baseline AudioLabel.db → 存两者路径
B. 比对:  按 §2 三层(标签类型/per‑type 版本分支/结构)比对复刻↔引擎,列当轮待同步项
          (重点:eTagType switch 缺 case(§2.1) + 各标签 dwVersion 分支上限(§2.2,遍布各标签);
           先核实是否真序列化进 .tani;区分"字节布局分支"与"运行时默认分支")
C. 改码:  改 Tani.cpp/HeaderTani.h/Tani.h(UTF-8,Edit/Write 安全)同步该标签/版本/结构;
          同步时逐条核 §3 两类信息(路径/音频)是否补齐;每段 SkipData 总字节数要对齐引擎
D. 编译:  §4 先编 RUST 依赖(KESMBase/ClipLib,§4 前置)→ 再 MSBuild rebuild FileParse.sln;编译失败 → 修编译错回到 C(LNK1104查遗留进程或RUST lib没编)
E. 测试:  用 baseline 同一份清单 → 跑扫描器得 current ScanResult.db
          + 跑 SearchAudioLabel 得 current AudioLabel.db(不同文件名!)
F. 判据:  diff_tani.py baseline vs current --audiolabel baseline_audio current_audio
          - 有意外差异(disappeared/new_fail/非目标 changed/非目标音频丢失) → 回滚本轮改动,回到 B
          - 差异全部裁定为预期 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 差异全部预期 → 完成
          写报告 UpdateCodeTani.md(§9),再汇报
```

> **只有真正改了代码才写报告**(§9)。三层已对齐、没改码(如纯健康基线检查),不写报告、只在对话里说明。

护栏(同 Pss/kmsc):
- **迭代上限:最多 8 轮**。8 轮仍未清零或反复异常,停止并汇报当前状态(别死循环)。
- **B 编译错优先**:编译不过绝不进测试。
- **C 回滚要干净**:有意外差异时把 `Tani.cpp`/`HeaderTani.h`/`Tani.h` 恢复到本轮改前状态(改前 `cp` 备份到临时目录最稳)。
- **D 编码**:源码 UTF-8 可 Edit/Write;`ScanFileList_tani.txt`、`.cmd` 是 GBK,**只用脚本/GBK 感知方式写,别用 Edit/Write**。
- **E 全量是默认**:~5.6 万文件/轮,实测约十几秒(见 §5),不慢。想对单个新标签先快速试错,可用 `regen_scanlist.py --subset` 缩小清单;但终止判据仍以全量无意外差异为准,子集只用于迭代试错。
- **F 两类信息**:每轮同步后核 §3 两类(路径/音频)是否补齐——这是"假成功"主要来源(tani 无数值汇总,别找第三类)。
- **G 不改引擎**:引擎文件只读对标,绝不修改。

---

## 8. 汇报格式（收尾时给用户，同 Pss/kmsc）

1. 同步了哪些标签类型/版本分支/结构(逐项:引擎文件:行 → 复刻文件:行,补了哪个 `ANIMTAG_*` case + per‑type 读取/版本分支 + 两类信息登记)。
2. 编译状态 + 测试范围(全量 ~5.6 万,耗时)。
3. 差异对比:baseline vs current 的 `changed/appeared/disappeared/still_failing/new_fail` 计数 + 音频 `audio_only_baseline/audio_only_current`;known-bad 清单。
4. 终止结论:差异是否清零、差异是否全部预期;撞上限则说明卡在哪轮/哪个标签。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后(类比 `CodeReviewKMSC` 的截断判断法),给出下一步。

---

## 9. 对比测试报告（落盘 UpdateCodeTani.md）

按 `CodeReviewTani.md` §5/§6 要求,真正改了代码后,闭环收尾把报告写到:
`项目路径\x64\Release\logs\UpdateCodeTani.md`(UTF‑8,**覆盖式**,一次改码任务一份)。

报告必须包含(同 Pss 但**不关注 Pss 表**,重点是 `Result`/`FileList` + AudioLabel):
1. **Scan.log 进程状态**:baseline 与 current 报告目录的 `Scan.log` 最后一行是否有 `日志正常关闭`;没有 = `Jx3SvnHookCheckTool.exe` 执行失败。
2. **ScanResult.db 逐表对比**:表 `FileList`/`Result` 内容——相同、不同,及不同原因(**不关注 Pss 表**)。
3. **AudioLabel.db 逐表对比**:`File`/`FilterKmsc`/`LogInfo`/`MovieKrlTxt`/`NewMovieInfo` 内容——相同、不同,及不同原因。

### 9.1 报告生成方式(脚本 + Claude 分工,同 Pss/kmsc)
```bash
REPO="$(pwd -W)"
python ".claude/skills/tani代码同步/scripts/gen_report_tani.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-audio "<baseline AudioLabel.db>" --current-audio "<current AudioLabel.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "$REPO/x64/Release/logs/UpdateCodeTani.md"
```
- 脚本逐表对比 ScanResult(FileList/Result,**不关注 Pss 表**)+ AudioLabel(File/FilterKmsc/LogInfo/MovieKrlTxt/NewMovieInfo)+ 检查 Scan.log,输出 md 片段(UTF‑8)。
- 脚本只给数字和样本,**"代码改动说明"和"不同原因"由 Claude 据本次改动补写**在脚本片段之上。

### 9.2 UpdateCodeTani.md 结构(参考 Pss/kmsc 的 UpdateCodePss/UpdateCodeKmsc.md 范式)
```
# Tani 代码修改前后对比测试报告
> 生成日期 / 对比 baseline vs current / 全量 ~5.6 万 tani

## 一、本次代码改动            ← Claude 写(引擎文件:行 → 复刻文件:行,补了什么)
## 二、前后对比结果             ← gen_report_tani.py 脚本片段(Scan.log + ScanResult[不关注Pss] + AudioLabel)
## 三、不同原因分析             ← Claude 写(逐表解释为什么不同,与本次改动的因果)
## 四、终止结论                 ← Claude 写(差异清零/无回归/是否撞上限;遗留建议)
```
- "二"由脚本 `>>` 追加;"一/三/四"由 Claude 写在片段上下。
- 报告 UTF-8(用 Write/Edit),**不是 GBK**——中文要正常显示。

**⚠️ "三、不同原因分析"必须详细说明差异来源**(不只列数字):
- 对每个有差异的表/字段,**说清差异从哪来**——是本次代码改动导致的(如"修复 SFX 标签漏抽,使 X 个 tani 的 .sfx 依赖从 0 变 N")、还是数据本身变动、还是工具行为差异。
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

# 生成全量 GBK tani 清单(深扫整个 client 下 .tani)
python ".claude/skills/tani代码同步/scripts/regen_scanlist.py" \
  --root "$JX3_HD_Client" --ext tani \
  --out   "x64/Release/logs/ScanFileList_tani.txt"

# 编译(先编 RUST 依赖 KESMBase/ClipLib,再编 FileParse.sln;FileParse.sln 不含这两个工程)
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" \
  FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal

# 全量扫描(ReadFileListFromSvnDB=0 走 ScanByFileList)
cd "x64/Release"
WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"
[ -f "$WCDB" ] || { echo "异常:svn wc.db 两个候选都不存在,技能终止"; exit 1; }  # 上级/本级 .svn 必须存在一个(§1 前置已查,此为兜底)
ReadFileListFromSvnDB=0 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe \
  "$JX3_HD_Client" \
  "$WCDB" \
  "$REPO/x64/Release/logs/ScanFileList_tani.txt"

# 音频标签扫描(前后用不同 db 文件名!InitDB 会先删同名 db)
cd "x64/Release"
ForDebug=0 ./KSearchResource.exe SearchAudioLabel \
  "$JX3_HD_Client" \
  "x64/Release/logs/AudioLabel_tani_baseline.db"   # current 轮换 _current.db

# 最新报告目录
ls -t "logs/JX3/trunk/" | head -1

# 差异对比(失败集+依赖+音频,纯差异不判好坏)
python ".claude/skills/tani代码同步/scripts/diff_tani.py" \
  "<baseline ScanResult.db>" "<current ScanResult.db>" \
  --audiolabel "<baseline AudioLabel.db>" "<current AudioLabel.db>"

# 生成对比报告片段(ScanResult[不关注Pss]+AudioLabel+Scan.log)
python ".claude/skills/tani代码同步/scripts/gen_report_tani.py" \
  --baseline-scan "<baseline ScanResult.db>" --current-scan "<current ScanResult.db>" \
  --baseline-audio "<baseline AudioLabel.db>" --current-audio "<current AudioLabel.db>" \
  --baseline-log "<baseline报告目录>/Scan.log" --current-log "<current报告目录>/Scan.log" \
  >> "x64/Release/logs/UpdateCodeTani.md"   # Claude 再补"代码改动/不同原因/结论"于其上
```
