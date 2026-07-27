# 代码同步技能总规律（7 技能对比 + 新建配方）

> 本文档总结 `KResourceReader` 已建的 7 个"代码同步"技能(Pss / kmsc / Ani / tani / krl / SRScene / State)的共通骨架与关键差异,作为:
> 1. **回顾索引**——一眼看清各技能异同(不用翻 7 份 SKILL.md);
> 2. **新建配方**——将来加新文件类型技能时照此快速生成,不用从头想;
> 3. **避坑清单**——已踩的坑集中记录。
>
> 各技能完整规范见 `CodeReview<Pss/Kmsc/Ani/Tani/Krl/SRScene/State>.md`,技能本体见 `d:\StudyAndroid\MySkill\skills\<技能>\SKILL.md`。

---

## 1. 七技能一览

| 技能 | 复刻函数 | 引擎原函数 | 扫描目录(`$JX3_HD_Client` 下) | 扩展名(磁盘) | 文件数 | 耗时/轮 |
|---|---|---|---|---|---|---|
| Pss | `Pss::ReadFile` | `KG3D_ParticleFileData::LoadFromFile` | `data/source/other` | `.pss`(小写) | ~4.16万 | ~10-15s |
| kmsc | `Kmsc::ReadFile` | `KPlotLoader::LoadPlotData` | `data/movie` | `.kmsc`(小写) | ~1039 | ~5s |
| Ani | `Ani::ReadFile` | `KG3D_Animation::LoadFromFile` | 整个 client(深扫) | `.ani`(小写) | ~23万 | ~47s |
| tani | `Tani::ReadFile` | `KG3D_AnimationTani_Data::LoadFromFile` | 整个 client(深扫) | `.tani`(小写) | ~5.6万 | ~6s |
| krl | `KRL::ReadFile` | `KGRLLoader::LoadUnitFromFile` | `represent/rl` | `.krl`(小写) | ~7.7万 | ~12s |
| SRScene | `SRScene::ReadFile` | `KSRScene::LoadFromFile` | `data/source/maps` | `.SRScene`(**大写**,注册小写 `srscene`) | ~434 | ~0.9s |
| State | `State::ReadFile` | `KG3D_LoadStateFileData` | `data/source/maps_source` | `.state`(小写) | ~668 | ~9.4s(`=1`) |

> 文件数/耗时是 2026-07-24 本机实测,换机器/数据更新会变,以实跑为准。

---

## 2. 关键差异矩阵（决定每个技能不同的 7 个维度）

| 维度 | Pss | kmsc | Ani | tani | krl | SRScene | State |
|---|---|---|---|---|---|---|---|
| **抽取信息类** | 三类 | 两类 | 一类(数值) | 两类 | 一类 | 一类 | 一类 |
| **有音频** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **有数值汇总** | ✅(PssInfo) | ❌ | ✅(BoneCnt等) | ❌ | ❌ | ❌ | ❌ |
| **抽路径** | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **调用路径** | reader工厂 | reader工厂 | **GetAniInfo专用** | reader工厂 | reader工厂 | reader工厂 | reader工厂 |
| **结构/枚举维护** | 自维护 | 自维护副本 | 自维护 | 自维护 | 自维护 | 自维护 | 自维护 |
| **default 行为** | 硬失败 | **硬失败**(NewAction) | 不硬失败(打印) | **硬失败**(顶层) | 软失败(OLDER_KRL) | 文件头校验,无default | 不校验version |
| **专门成功表** | Pss表+PssLoop | 无(Result双判据) | Ani表+AniMask | 无 | 无 | 无 | 无 |
| **diff 风格** | regressed判断式 | 纯差异 | 纯差异 | 纯差异 | 纯差异 | 纯差异 | 纯差异 |

### 2.1 各维度说明

**抽取信息类(§3,最核心差异)**:
- **三类**(Pss):明文路径 + 音频标签 + 特效数值汇总(`m_pssInfo`/成员计数器,落 `Pss` 表)。
- **两类**(kmsc/tani):明文路径 + 音频标签(无数值汇总)。
- **一类·数值**(Ani):只抽 `m_dwType`/`m_dwNumBones`/`m_dwNumAnimatedVertices`/`m_bKeyFrame`/`m_dwMask` 等数值成员(落 `Ani` 表),**无路径、无音频**。
- **一类·路径**(krl/SRScene/State):只抽明文依赖路径(无音频、无数值汇总)。krl=mesh/mtl/ani/portrait;SRScene=SMTemplate;State=model/ani/socket mesh/mtl/ani。

**调用路径**:
- 6 个技能经 reader 工厂 `AddFileType("<ext>", &ProcessXxx)`(`Jx3ResFileReaderAPI.cpp`)→ `return new ...` → `ReadFile`。grep `AddFileType` 能找到扩展名。
- **Ani 特殊**:不经 `AddFileType`(注册表无 "ani"),经 `KResChecker→GetAniInfo→KBase::GetAniInfo→Ani::ScanFile→ReadFile` 专用路径。grep `AddFileType` 找不到 ani 是正常的。

**结构/枚举维护**:**7 个全部自维护副本**(在各自 `<Header>.h`/`.h` 里 `typedef struct`/`enum class` 直接定义,非 `#include` 引擎头)。
- ⚠️ kmsc 的 `KmscHeader.h` 里 `EnumObjectType`/`EnumActionType` 是**自维护副本**(顶部注释 `//Sword3\Include\KG3DMovie\IKMovieTypeDef.h` 标明来源,但**不是 include**),落后风险在枚举值没跟引擎 + `NewObject`/`NewAction` switch case。
- ⚠️ 引擎头(krl 的 `KGRLFormat.h`、SRScene/State 的头等)经 include 路径解析,**本机未必能直接 Read**;比对时以引擎 `.cpp` 的 `Reference(sizeof(...))`/`_ReadBuffer`/字段访问反推字节数,与复刻 `.h` 副本核对。

**default 行为(决定落后表现)**:
- **硬失败**(`KG_PROCESS_ERROR(false)`,缺 case 挂整个文件):kmsc(`NewAction`)、tani(顶层 `eTagType`)、Pss。落后 = **解析失败**暴露快。
- **软失败**(`OnErrorByGBK(ERROR_TYPE_OLDER_KRL)` 只报"工具版本太老"不挂):krl。落后 = 漏抽/版本外。
- **不硬失败**(落 default 只打印 unsupport、漏抽但不挂):Ani。落后 = 漏抽/读错。
- **文件头校验但无版本 default**:SRScene(文件头 `dwVersion` 恒 0,entity 内 `>=1/>=2` 是版本分支无 default)。
- **不校验 version/无硬失败**:State(注释掉 `dwVersion` 校验)。

**diff 风格**:
- **Pss**:`regressed`/`improved`/`audio_removed` **判断式**(字段变=回归→exit1)。因为 Pss 有数值汇总表,字段变了能判好坏。
- **其余 6 个**:`changed`/`appeared`/`disappeared`/`still_failing`/`new_fail` **纯差异**(不判好坏,exit1 仅 `new_fail`)。因无成功表/只抽路径,字段变不好判好坏,交人工裁定。资源对错由复刻 `.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报,不是 diff 职责。

---

## 3. §2 差异比对层（各技能比对口径）

| 技能 | §2 层 | 普遍落后来源 |
|---|---|---|
| Pss | 2.1元素块FEID / 2.2发射器类型 / 2.3模块 / 2.4结构 / 2.5版本分支 | 版本分支层 |
| kmsc | 2.1枚举 / 2.2对象类型NewObject / 2.3动作类型NewAction / 2.4结构 / 2.5版本分支 | NewAction缺case(硬失败)+版本分支 |
| Ani | 2.1类型(KG3D_ANIMATION_TYPE) / 2.2mask(ANI_FILE_MASK_*) / 2.3结构 | mask新版本格式 |
| tani | 2.1标签类型(eTagType) / 2.2 per-tag版本分支 / 2.3结构 | per-tag版本分支 |
| krl | 2.1版本层(V0-V5 switch) / 2.2 per-version结构 / 2.3文件头常量 | V6+新版本 |
| SRScene | 2.1文件头 / 2.2 per-entity版本分支 / 2.3结构 | entity dwVersion>=3 |
| State | 2.1文件头dwExtend布局 / 2.2 per-state版本分支 / 2.3只读state段边界 | state dwVersion>=0x05 + dwExtend[4]stringStart错位 |

**通用规律**:
1. **版本分支层是普遍落后来源**(所有技能都有):版本标识数字(新版本号>老版本)遍布解析全程,引擎新版本在 `>=N`/`==N` 分支加字段,复刻没跟就错位/漏抽。§2 比对都要有"版本分支层",grep 版本号核分支上限。
2. **"字节布局分支" vs "运行时默认分支" 必须区分**(tani/krl/SRScene/State 通用陷阱):
   - **字节布局分支**(`dwVersion>=N` 决定读几字节):复刻**必须对齐**,否则后续错位。
   - **运行时默认分支**(读字段后按内部 `uVersion` 设运行时默认值,如 SFX `if(uVersion<20230404) bScaleByShape=TRUE`、CameraAni `if(dwVersion<2) bUseByTrack=TRUE`,不改字节):复刻**不需要同步**,用 `SkipData` 跳过即可。
   - 判定法:看该分支是否改变 `Reference`/`CopyData`/`SkipData`/`Read` 的**字节数**。改变=要对齐;只改运行时变量=跳过。
3. **SkipData 折叠对齐**(krl/tani/SRScene/State):复刻只抽路径/音频,用 `SkipData` 跳过不要的运行时字段、折叠进大 `SkipData(DWORD*N)`;引擎逐字段 `CopyData` 读 + 设默认。比对核心是**每段字节总数对齐**,不是逐字段读取方式相同。复刻一段 `SkipData(BOOL)+SkipData(int)+SkipData(DWORD*26)` 与引擎 `CopyData×7+Seek(DWORD*25)` 只要**总字节数相等**即对齐。

---

## 4. 共通骨架（所有技能一样的部分）

以下 7 个技能完全一致,新建技能直接套:

### 4.1 前置环境检查(§1,6 项)
4 环境变量 + MSBuildTool + svn wc.db,任一缺失报错终止:
```bash
for v in JX3ENGINE_Sword3 JX3ENGINE_BASE JX3ENGINE_DevEnv JX3_HD_Client; do [ -d "${!v}" ] && echo "$v OK=${!v}" || echo "$v 缺失,技能终止"; done
[ -f "$MSBuildTool" ] && echo "MSBuildTool OK" || echo "MSBuildTool 缺失,技能终止"
WCDB="$JX3_HD_Client/../.svn/wc.db"; [ -f "$WCDB" ] || WCDB="$JX3_HD_Client/.svn/wc.db"; [ -f "$WCDB" ] && echo "wc.db OK" || echo "wc.db 异常,技能终止"
```

### 4.2 项目路径 / REPO
- 仓库根 = SKILL.md 上溯 4 级 = Claude cwd(Primary working directory)。
- bash 块 `REPO="$(pwd -W)"`(Windows 绝对,exe 能接受)。
- ⚠️ **REPO 必须从仓库根取,勿在 `x64/Release` 里用 `cd .. && pwd -W` 取**(得 `仓库根/x64` 多一层 → 拼出 `x64/x64/Release/...` 文件不存在 → `MainScan GetLastError(3)` 扫 0 文件)。

### 4.3 构建(§4,含 RUST 前置)
```bash
# 先编 RUST 依赖(FileParse.sln 不含这两个工程,不会自动先编)
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
# 再编主解决方案(bash 下 / 写成 //)
"$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
```
- 不用 `Build.cmd`(带 svn up/git 推送/PE 核验副作用)。
- LNK1104 打不开 dll/exe → 查遗留 `Jx3*` 进程(`tasklist | grep Jx3` + `taskkill //PID //F`)或 RUST lib 没编。

### 4.4 测试(§5)
- **清单**:`ScanFileList_<ext>.txt` 必须 GBK(cp936)+CRLF,用 `scripts/regen_scanlist.py` 生成(**别用 Edit/Write**,UTF-8 破坏中文)。
- **扫描**:`ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe <client> <wc.db> <清单>`。
  - `=1` 走 `CopyDataFromWCDBList`(清单 INNER JOIN svn wc.db 取元信息填 FileList,再解析),**仍扫清单全量,不漏文件**,FileList 多带 changed_revision/date/author,多 ~8s 查 svn db。
  - ⚠️ 勿误以为 `=1` 是增量只扫改动——错。详见 `feedback_readfilelist_fromsvndb_semantics`。
- **音频扫描**(仅有音频的 Pss/kmsc/tani):`KSearchResource.exe SearchAudioLabel <client> <AudioLabel_<ext>_baseline/current.db>`,前后**不同 db 文件名**(InitDB 先删同名),跑完**保留禁删**。

### 4.5 闭环(§7)
```
0.前置(6项) → A.基线(baseline ScanResult [+AudioLabel]) → B.比对(§2列待同步项)
→ C.改码 → D.编译(RUST前置+FileParse.sln) → E.current(同清单[+AudioLabel]) → F.diff判据
→ 有意外差异回滚回B / 无则回B看剩余 → G.终止:写UpdateCode<Ext>.md再汇报
```
- **只有真正改了代码才写报告**(§9)。已对齐没改码(健康基线)不写报告,只在对话说明。
- 迭代上限 8 轮;编译错优先;回滚要干净(改前 `cp` 备份);不改引擎。

### 4.6 编码
- 源码 UTF-8:Edit/Write 安全。
- `ScanFileList_*.txt`、`.cmd`:GBK,**只用脚本/GBK 感知方式写**(Python `open(...,encoding='gbk')`),别用 Edit/Write。
- 报告 `UpdateCode<Ext>.md`:UTF-8,Edit/Write 安全。

### 4.7 技能源维护口径
- **只维护 `d:\StudyAndroid\MySkill\skills\<技能>\`**(MySkill git 仓库源),不碰仓库内 `...\KResourceReader\.claude\skills\` 那份。
- 仓库内 `.claude/skills/<技能>` 是 junction 软链 → MySkill,跑 `d:\StudyAndroid\MySkill\建立软连接.cmd` 建(该 .cmd 用 `call :MakePathLink <技能名>` 列各技能,GBK+CRLF)。
- ⚠️ Pss 在仓库内是**独立旧副本(真目录,非软链)**,与 MySkill 未对齐——按既定保持现状,改 Pss 只改 MySkill 源。

### 4.8 脚本三件套(每技能 `scripts/`)
- `regen_scanlist.py`:通用共享,`--root`/`--ext`/`--out`/`--subset`/`--dry-run`,默认根取自 `$JX3_HD_Client` 环境变量(**无硬编码兜底**,env 未设且不传 `--root` → exit 2)。ext 大小写不敏感(`.lower()` 比),匹配磁盘大写扩展名(如 `.SRScene`)。
- `diff_<ext>.py`:纯差异(Pss 除外,判断式),`--knownbad`/`--json`/`--quiet`,exit1 仅 `new_fail`。
- `gen_report_<ext>.py`:逐表对比 ScanResult(FileList/Result,**不关注 Pss 表**)+ 可选 AudioLabel(有音频的)+ 检查 Scan.log,输出 md 片段供 `UpdateCode<Ext>.md`。

---

## 5. 新建技能配方（拿到新文件类型怎么定）

加第 8 个技能(如 `.foo`),按此流程:

### 5.1 先读两侧源码,定 7 个差异维度
1. **复刻**:`src/<Foo>/Foo.cpp` 的 `Foo::ReadFile`;引擎原函数(查 `CodeReviewFoo.md` 给的路径)。
2. **抽取类**:grep `OnReadResourceFileByGBK`(有=抽路径)、`AddWwiseEvent`/`AddFmod`(有=抽音频)、是否有数值汇总成员(落专门表)。→ 定 §3 是几类。
3. **调用路径**:grep `AddFileType("<ext>"` 在 `Jx3ResFileReaderAPI.cpp`;找不到则查是否经 `Get<X>Info` 专用路径(像 Ani)。
4. **结构维护**:看复刻 `<Header>.h` 是 `typedef struct`/`enum`(自维护)还是 `#include` 引擎头。
5. **default 行为**:看复刻 `switch` 的 `default` 是 `KG_PROCESS_ERROR(false)`(硬失败)/`OnErrorByGBK(...OLDER...)`(软失败)/只打印(不硬失败)/无校验。
6. **专门成功表**:grep 扫描器源/实测一个 db,看有无 `Foo` 表(有则 diff 用它,无则用 Result 双判据)。
7. **§2 比对层**:读引擎 `LoadFromFile` 的分派结构(switch 类型/版本/结构),定几层;**必含版本分支层**。

### 5.2 实测确认
- 扩展名大小写:`find $JX3_HD_Client/<dir> -iname "*.<ext>"` 看磁盘真实大小写(注册名小写,磁盘可能大写如 `.SRScene`)。
- 文件数 + 目录:`--dry-run` 统计。
- 依赖类型分布:跑一次扫描看 `Result` 的 `SonExtName`。

### 5.3 套模板写
- 复制最接近的技能目录(无音频+路径→krl/SRScene/State;有音频→tani/kmsc;抽数值→Ani)。
- 改:§1 路径、§2 比对层(自己总结,spec 留空)、§3 抽取类、§5 扫描目录/ext、脚本 ext、报告名。
- 沿用 §4 共通骨架(别改:前置/REPO/RUST前置/`=1`/闭环/编码/维护口径)。
- `regen_scanlist.py` 的 `_DEFAULT_ROOT` 用 `$JX3_HD_Client/<该技能子目录>`、`--ext` 默认。
- 补 `建立软连接.cmd` 加新技能行(**GBK+CRLF 感知**,用 Python `open('rb').decode('gbk')` 改写,行尾保持 CRLF,否则 cmd 粘连跳行——已踩过)。

### 5.4 验证
- 3 脚本 `py_compile` + `--help` + 真实 db 自比 exit 0。
- 零硬编码检查(`grep sword3-products/D:\JX3` 应 0)。
- `regen` env 未设 exit 2。
- 跑 `建立软连接.cmd` 建软链 → 技能进可用列表 → 全链路测试。

---

## 6. 已踩坑清单（feedback 类,新建/跑技能必看）

| 坑 | 表现 | 解 | 记忆 |
|---|---|---|---|
| REPO 取错 | 扫描 0s 退出、`GetLastError(3)` 扫 0 文件 | 从仓库根 `pwd -W` 取,别在 `x64/Release` 里 `cd ..` | SKILL §5.2 gotcha |
| RUST dll 缺 | 扫描 0s、`LoadEngineDLL GetLastError(126)` | 跑 §4 RUST 前置 + rebuild FileParse.sln 触发 PostBuild 拷 dll | `feedback_rust_dep_build_prereq` |
| GBK 文件用 Edit/Write | `.cmd`/清单中文乱码 | 用 Python `open(encoding='gbk')` 改;源码 UTF-8 才用 Edit/Write | `feedback_gbk_file_edit` |
| .cmd 改 CRLF 丢 CR | `建立软连接.cmd` 新增行 cmd 粘连、跳行不执行 | Python 改 GBK 文件时保持 CRLF(`\r\n`),别只写 `\n` | (本次新踩) |
| ReadFileListFromSvnDB 误判 | 以为 `=1` 是增量只扫改动 | `=1` 是清单 JOIN svn db 取元信息,仍全量;用户钦定用 `=1` | `feedback_readfilelist_fromsvndb_semantics` |
| 跳过运行时默认当落后 | 把"复刻没设运行时默认"当差异同步 | 区分字节布局分支(要对齐)vs 运行时默认分支(SkipData 跳过) | SKILL §2 通用口径 |
| 字段变当回归 | Pss 外技能用 regressed 判断式误判 | 无成功表的用纯差异,字段变交人工裁定 | diff 脚本设计 |
| 保留 AudioLabel.db | 跑完删了没法复算 | AudioLabel*.db 是技能输出,保留禁删,只清 ScanFileList 中间产物 | `feedback_keep_skill_output_db` |

---

## 7. 跨技能通用口径（写进每个 SKILL 的共性条款）

1. **§2 必有版本分支层**:版本标识数字(新>老)遍布解析全程,引擎新版本加分支/字段复刻没跟就错位漏抽;grep 版本号核分支上限。
2. **字节布局 vs 运行时默认**:比对时区分——改变字节数的分支要对齐;只改运行时变量值的分支复刻跳过即可。
3. **SkipData 折叠对齐**:复刻只抽需要的信息,跳过字段折叠进大 SkipData;比总字节数相等,不比逐字段读取方式。
4. **"switch 缺 case" ≠ "必须同步"**:先核实该类型/版本是否真被序列化进文件(引擎有 reader+SaveToFile 写入才算),编辑器-only/不写盘的不同步。
5. **不改引擎**:引擎文件只读对标,绝不修改。
6. **资源对错由解析时报,diff 不判**:复刻 `.cpp` 解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报资源对错,diff 只列数据差异、不判好坏(除 Pss 有数值表可判)。

---

## 8. 记忆索引（跨会话持久,新建技能前先读）

- `project_pss_sync_skill` / `project_kmsc_sync_skill` / `project_ani_sync_skill` / `project_tani_sync_skill` / `project_krl_sync_skill` / `project_srscene_sync_skill` / `project_state_sync_skill`——各技能位置、与 Pss 差异、首次实测。
- `project_pss_replica_lag`——复刻落后引擎的普遍机制。
- `feedback_version_branch_sync`——版本分支层是普遍落后来源。
- `feedback_rust_dep_build_prereq`——RUST 前置编译。
- `feedback_readfilelist_fromsvndb_semantics`——`=0`/`=1` 语义。
- `feedback_gbk_file_edit`——GBK 文件别用 Edit/Write。
- `feedback_keep_skill_output_db`——保留 AudioLabel.db。
- `feedback_pe_version_check`——PE 版本自检(发布管线,闭环跳过)。
- `project_encoding_split`——源码 UTF-8、数据 GBK。
- `project_dev_machine`——64GB 机器,内存调优可取大值。

> 本文档与上述记忆互补:记忆是"一条事实一个文件"的细粒度持久,本文档是"7 技能总规律"的结构化总览。新建技能时先读本文档定维度,再读对应记忆/CodeReview<Ext>.md 细节。
