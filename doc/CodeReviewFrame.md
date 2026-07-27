# 代码同步技能框架（可复用骨架模板）

> 本文档把 `KResourceReader` 的 7 个"代码同步"技能(Pss/kmsc/Ani/tani/krl/SRScene/State)**抽象成一套可填充的骨架**,目标是:
> - **抽象共性**——所有技能共有的、不可变的骨架(前置/构建/闭环/编码/维护口径);
> - **提取槽位**——每个技能需要按文件类型填充的可变点(§2 比对法/§3 抽取类/扫描目录/扩展名…);
> - **区分差异的判别式**——拿到新文件类型,用一组判别问题定每个槽位怎么填。
>
> 与 `CodeReview.md` 的分工:`CodeReview.md` 是"7 技能横向对比 + 新建配方"(看具体值),本文档是"骨架结构 + 槽位定义 + 判别式"(看抽象结构,不带具体技能值)。新建技能时两份配合用:本文档定结构,`CodeReview.md` 查同类技能的填法。
>
> 各技能完整规范见 `CodeReview<Ext>.md`,本体见 `d:\StudyAndroid\MySkill\skills\<技能>\SKILL.md`。

---

## 0. 一句话定义

一个"代码同步"技能 = **把复刻解析器(`<Ext>::ReadFile`)与引擎原函数(`<Engine>::LoadFromFile`)对齐的全自动闭环**:比对差异 → 改复刻 → 编译 → 全量测试 → 前后对比 → 不通过回滚,循环到差异清零且无意外差异。过程中守住该文件类型的信息抽取口径(路径/音频/数值)。

所有技能共享同一闭环骨架(§2),差异只在 6 个可填充槽位(§3)。

---

## 1. 骨架总览：9 节固定结构

每个技能 SKILL.md 都是这 9 节,**节号/标题固定,内容按槽位填**:

| 节 | 标题 | 性质 | 内容来源 |
|---|---|---|---|
| §1 | 锁定路径(别取错) | **固定** | 前置环境检查(6项)+ 项目路径 + 复刻侧 + 引擎侧(只填路径) |
| §2 | 差异比对法(每轮第一步) | **槽位**:层数+各层口径自定 | 读两侧源码总结(规范留空要我总结) |
| §3 | 信息抽取(同步不变量,必须守) | **槽位**:几类+各类登记点 | 按文件类型定(三类/两类/一类) |
| §4 | 构建 | **固定** | RUST 前置 + FileParse.sln rebuild |
| §5 | 测试(全量) | **槽位**:扫描目录+扩展名+有无音频 | 按文件类型定;清单/扫描/报告读法固定 |
| §6 | 差异对比(看变化) | **槽位**:diff 风格(判断式/纯差异)+ 有无音频对比 | 按有无成功表/音频定 |
| §7 | 全自动闭环流程 | **固定** | 0-A-B-C-D-E-F-G 七步 |
| §8 | 汇报格式 | **固定** | 5 项汇报内容 |
| §9 | 对比测试报告(落盘) | **固定结构,槽位**:报告名/有无音频表 | 脚本>>片段 + Claude 补一/三/四 |
| 附 | 快速命令速查 | **固定结构,槽位**:目录/ext/脚本名 | 同 §5 命令的速查版 |

**固定节** = 7 个技能一字不差(只改路径/扩展名等局部变量),直接复制。
**槽位节** = 按文件类型填,但填法有判别式(§3)。

---

## 2. 共性骨架（不可变部分，所有技能一样）

### 2.1 §1 前置环境检查（6 项,固定）
4 环境变量 + MSBuildTool + svn wc.db,任一缺失报错终止:
- `JX3ENGINE_Sword3`(引擎源码根)/`JX3ENGINE_BASE`/`JX3ENGINE_DevEnv`(编译 include)/`JX3_HD_Client`(client 数据根)/`MSBuildTool`(MSBuild.exe)/svn `wc.db`(`$JX3_HD_Client/../.svn/wc.db` 或 `$JX3_HD_Client/.svn/wc.db` 之一)。
- 检查命令 bash 固定写法(见任一 SKILL §1)。任一缺失 → 报错终止,不继续。

### 2.2 §1 项目路径 / REPO（固定 + gotcha）
- 仓库根 = SKILL.md 上溯 4 级 = Claude cwd。
- `REPO="$(pwd -W)"`(Windows 绝对,exe 能接受)。
- ⚠️ **gotcha**:REPO 必须从仓库根取,勿在 `x64/Release` 里 `cd .. && pwd -W` 取(得 `仓库根/x64` 多一层 → 拼出 `x64/x64/Release/...` 文件不存在 → `MainScan GetLastError(3)` 扫 0 文件、45ms 退出)。

### 2.3 §4 构建（固定：RUST 前置 + FileParse.sln）
```bash
# 先编 RUST 依赖(FileParse.sln 不含这两个工程,不会自动先编;lib 缺→LNK1104 / dll 缺→GetLastError(126))
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
"$MSBuildTool" "$JX3ENGINE_Sword3/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
# 再编主解决方案(bash 下 / 写成 //)
"$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
```
- 不用 `Build.cmd`(带 svn up/git 推送/PE 核验副作用)。
- LNK1104 → 查遗留 `Jx3*` 进程或 RUST lib 没编。

### 2.4 §5 测试（固定流程,槽位填目录/ext）
- **清单**:`ScanFileList_<ext>.txt` 必须 **GBK(cp936)+CRLF**,用 `scripts/regen_scanlist.py` 生成(**别用 Edit/Write**,UTF-8 破坏中文)。
- **扫描**:`ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe <client> <wc.db> <清单>`。
  - `=1` 走 `CopyDataFromWCDBList`(清单 INNER JOIN svn wc.db 取元信息,再解析),**仍扫清单全量不漏文件**,FileList 多带 svn 元信息,多 ~8s。勿误以为 `=1` 是增量。
- **音频扫描**(仅有音频的技能):`KSearchResource.exe SearchAudioLabel <client> <AudioLabel_<ext>_baseline/current.db>`,前后**不同 db 文件名**(InitDB 先删同名),跑完**保留禁删**。
- **报告目录**:`logs/JX3/trunk/<时间戳>/`,`Scan.log` 末尾应含"日志正常关闭"。

### 2.5 §7 闭环（固定七步）
```
0. 前置:  §1 六项检查,任一缺失 → 报错终止
A. 基线:  regen_scanlist.py 生成清单 → 跑扫描器(§5.2)得 baseline ScanResult.db
          [+ 有音频的跑 SearchAudioLabel 得 baseline AudioLabel.db] → 存路径
B. 比对:  按 §2 比对复刻↔引擎,列当轮待同步项(先核实是否真序列化;区分字节布局/运行时默认)
C. 改码:  改复刻 .cpp/.h(UTF-8,Edit/Write 安全)同步;同步时核 §3 抽取口径是否补齐;每段字节总数要对齐引擎
D. 编译:  §4 RUST 前置 + FileParse.sln rebuild;编译失败 → 修编译错回 C
E. 测试:  用 baseline 同一份清单 → 跑扫描器得 current ScanResult.db
          [+ 有音频的跑 SearchAudioLabel 得 current AudioLabel.db,不同文件名]
F. 判据:  diff_<ext>.py baseline vs current [--audiolabel ...]
          - 有意外差异 → 回滚本轮改动,回 B
          - 差异全部裁定为预期 → 本轮通过,回 B 看剩余项
G. 终止:  B 无待同步项 且 F 差异全部预期 → 完成
          写 UpdateCode<Ext>.md(§9),再汇报(§8)
```
- **只有真正改了代码才写报告**(§9)。已对齐没改码(健康基线)不写报告,只在对话说明。
- 护栏:迭代上限 8 轮;编译错优先;回滚要干净(改前 `cp` 备份);全量是默认(子集只用于试错);不改引擎。

### 2.6 §8 汇报（固定 5 项）
1. 同步了哪些类型/版本/结构(引擎文件:行 → 复刻文件:行,补了什么)。
2. 编译状态 + 测试范围(全量数,耗时)。
3. 差异对比:baseline vs current 的计数 + 音频(若有);known-bad 清单。
4. 终止结论:差异是否清零、是否全部预期;撞上限说明卡在哪轮/哪个类型。
5. 遗留建议:`still_failing` 且非 known-bad 的文件,逐个判断真坏文件 vs 复刻仍落后。

### 2.7 §9 报告（固定结构,脚本 + Claude 分工）
- 脚本 `gen_report_<ext>.py` `>>` 输出 md 片段(Scan.log 状态 + ScanResult 逐表对比 [+ AudioLabel 逐表对比,若有音频])。
- Claude 在脚本片段**之上**补"一、本次代码改动""三、不同原因分析""四、终止结论"(脚本只给数字和样本,给不出改动说明和原因)。
- 报告 UTF-8(Edit/Write 安全),**不是 GBK**。
- 报告结构:一(改动)/二(脚本片段)/三(原因)/四(结论)。

### 2.8 编码口径（固定）
- 源码 UTF-8:Edit/Write 安全。
- `ScanFileList_*.txt`、`.cmd`:GBK,**只用脚本/GBK 感知方式写**(Python `open(encoding='gbk')`),别用 Edit/Write。
- ⚠️ 改 GBK `.cmd` 保持 CRLF:Python 改时行尾写 `\r\n`,只写 `\n` 会让 cmd 粘连、跳行不执行(已踩)。

### 2.9 技能源维护口径（固定）
- **只维护 `d:\StudyAndroid\MySkill\skills\<技能>\`**(MySkill git 仓库源),不碰仓库内 `...\KResourceReader\.claude\skills\`。
- 仓库内 `.claude/skills/<技能>` 是 junction 软链 → MySkill,跑 `d:\StudyAndroid\MySkill\建立软连接.cmd` 建。
- ⚠️ Pss 仓库内是独立旧副本(真目录非软链),与 MySkill 未对齐——按既定保持现状,改 Pss 只改 MySkill 源。

---

## 3. 可填充槽位（差异部分,6 个槽位 + 判别式）

每个技能的差异全在这 6 个槽位。新建技能时,对每个槽位问一组判别问题定填法。

### 槽位 1：复刻/引擎路径 + 调用路径
**填**:
- 复刻函数:`src/<Ext>/<Ext>.cpp` 的 `<Ext>::ReadFile`(在 `Jx3ResFileReaderAPI.vcxproj`)。
- 引擎原函数:`<引擎路径>.cpp` 的 `<Engine>::LoadFromFile`(只读对标)。
- 调用路径:**判别**——grep `AddFileType("<ext>"` 在 `Jx3ResFileReaderAPI.cpp`:
  - 找到 → reader 工厂路径(`AddFileType` → `ProcessXxx` → `new <Ext>` → `ReadFile`),绝大多数技能走这条。
  - 找不到 → 查是否经 `Get<X>Info` 专用路径(`KResChecker→GetAniInfo→KBase::GetAniInfo→<Ext>::ScanFile→ReadFile`),目前只有 Ani 这么走。

### 槽位 2：§2 差异比对法（层数 + 各层口径,自己总结）
**规范留空要我总结**——读两侧源码,定比对层。判别:
- 引擎 `LoadFromFile` 怎么分派?
  - 按**类型枚举**分派(`switch(eType)`)→ 有"类型层"(grep 枚举两侧做 case 集合差)。
  - 按**文件头 version** 分派(`switch(version)`)→ 有"版本层"(grep `version` 两侧做 case 集合差)。
  - 按**per-item version** 分派(每 item 内 `if(dwVersion>=N)`)→ 有"per-item 版本分支层"(grep `>=N` 取两侧分支上限)。
- 必含**版本分支层**(普遍落后来源:新版本号>老,引擎新版本加字段,复刻没跟就错位)。
- 必含**结构层**(grep 结构体名比字段/大小/pack)。
- **通用口径**(写进每个技能 §2):
  - 区分"字节布局分支"(改变读字节数,要对齐) vs "运行时默认分支"(只改运行时变量值,复刻 SkipData 跳过)——判定法:看是否改变 `Reference`/`SkipData`/`Read` 字节数。
  - SkipData 折叠对齐:复刻跳过不要的字段折叠进大 SkipData;比**每段字节总数**相等,不比逐字段读取方式。
  - "switch 缺 case" ≠ "必须同步":先核实该类型/版本是否真被序列化进文件(引擎有 reader+SaveToFile 写入才算)。

### 槽位 3：§3 信息抽取（几类 + 各类登记点）
**判别**(grep 复刻 + 看落库):
| 信号 | 判定 |
|---|---|
| 有 `OnReadResourceFileByGBK(...)` 调用 | 抽**明文依赖路径**(落 ScanResult.db 的 Result 表) |
| 有 `AddWwiseEvent`/`AddFmod` 调用 | 抽**音频标签**(落独立 AudioLabel.db 的 File 表,需跑 SearchAudioLabel) |
| 有数值成员落专门表(如 Pss 的 PssInfo→Pss 表、Ani 的 BoneCnt→Ani 表) | 抽**数值汇总**(落专门成功表) |

→ 组合定 §3 几类:
- **三类**(路径+音频+数值):Pss。
- **两类**(路径+音频,无数值):kmsc/tani。
- **一类·数值**(只数值成员,无路径无音频):Ani。
- **一类·路径**(只路径,无音频无数值):krl/SRScene/State。
- ⚠️ 没有的类**别找**——如 krl/SRScene/State 无数值汇总,别照搬 Pss §3.3。

### 槽位 4：§5 扫描目录 + 扩展名 + 有无音频
**填**:
- 扫描目录:`find $JX3_HD_Client/<dir> -iname "*.<ext>"` 实测定(数据在哪个子目录)。
- 扩展名 + **大小写**:磁盘真实大小写(注册名都小写,磁盘可能大写如 `.SRScene`)。`regen_scanlist.py` 的 `--ext` 用 lower 比,大小写不敏感。
- 有无音频扫描:槽位 3 定的(有音频→§5.3 跑 SearchAudioLabel;无→§5.3 写"无")。

### 槽位 5：§6 diff 风格 + 有无音频对比
**判别**:
| 条件 | diff 风格 |
|---|---|
| 有专门成功表(Pss 的 Pss表/Ani 的 Ani表) + 字段变能判好坏 | **判断式**:`regressed`/`improved`/`audio_removed`,字段变=回归→exit1 |
| 无成功表(只抽路径,落 Result 双判据) / 字段变不好判好坏 | **纯差异**:`changed`/`appeared`/`disappeared`/`still_failing`/`new_fail`,exit1 仅 `new_fail` |
- 有音频 → diff 加 `--audiolabel <baseline.db> <current.db>`(比 `File` 表三元组);无 → 不加。
- **资源对错由复刻解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报,diff 不判**(纯差异技能的统一口径)。

### 槽位 6：§9 报告名 + 表集
- 报告名:`UpdateCode<Ext>.md`(覆盖式,一次改码任务一份)。
- ScanResult 表集:**所有技能都关注 FileList/Result,不关注 Pss 表**(Pss 技能自己关注 Pss 表,但不写在 gen_report 里——Pss 的 gen_report 比全表)。
- AudioLabel 表集:有音频的比 `File`/`FilterKmsc`/`LogInfo`/`MovieKrlTxt`/`NewMovieInfo`(Pss/kmsc/tani);无音频的无此节(Ani/krl/SRScene/State)。

---

## 4. default 行为谱系（影响落后表现,写进 §2/§5.4）

复刻 `switch`/校验的 `default` 行为决定落后怎么暴露,新建时看复刻源码定:

| default 行为 | 含义 | 落后表现 | 代表技能 |
|---|---|---|---|
| **硬失败**(`KG_PROCESS_ERROR(false)`) | 缺 case 挂整个文件 | 解析失败,暴露快 | kmsc(NewAction)/tani(顶层)/Pss |
| **软失败**(`OnErrorByGBK(...OLDER...)` 只报"工具版本太老") | 跳过该版本不挂 | 漏抽/版本外 | krl |
| **不硬失败**(落 default 只打印 unsupport) | 漏抽但不挂 | 漏抽/读错 | Ani |
| **文件头校验但无版本 default** | 文件头 version 恒值,per-item version 是分支 | 漏抽/错位 | SRScene |
| **不校验 version/无硬失败** | 不校验,直接取数 | 漏抽 | State |

> 写进 SKILL 时:§2 说明该技能 default 行为 + 落后表现;§5.4 说明 `ErrLevel=7` 失败的常见原因(硬失败=缺 case;软失败/不硬失败=少见,多文件损坏/越界)。

---

## 5. 脚本三件套（固定结构,槽位填 ext/目录/表集）

每个技能 `scripts/` 三脚本,**结构完全一致**,只改几处变量:

### 5.1 regen_scanlist.py（通用共享）
- 共享同一份(各技能副本),CLI:`--root`/`--out`/`--ext`/`--subset`/`--dry-run`。
- `_DEFAULT_ROOT = os.path.join(os.environ.get("JX3_HD_Client") or None, "<子目录>") if env else None`(**无硬编码兜底**,env 未设且不传 `--root` → exit 2)。
- `--ext` 默认 = 该技能扩展名;`collect_from_dir` 用 `fn.lower().endswith("." + ext.lower())`(大小写不敏感)。
- 输出 GBK+CRLF。
- **槽位**:`_DEFAULT_ROOT` 的子目录 + `--ext` 默认值。

### 5.2 diff_<ext>.py
- 结构:读 Result(`WHERE lower(File) LIKE '%.<ext>'`,大小写不敏感)得 failed/depend/scanned;可选 `--audiolabel` 读 AudioLabel File 表。
- 输出:changed/appeared/disappeared/still_failing/new_fail/stable(+ audio_only_b/c 若有音频)。
- exit:0 正常;1 `new_fail` 非空;2 输入异常。
- **槽位**:扩展名(大小写不敏感 LIKE)、有无 `--audiolabel`、diff 风格(判断式[有成功表,读专门表比字段] vs 纯差异[只比 Result 依赖集])。

### 5.3 gen_report_<ext>.py
- 结构:SCAN_TABLES(FileList/Result,**不关注 Pss 表**)+ 可选 AUDIO_TABLES(有音频)+ check_log + compare_table,输出 md 片段。
- **槽位**:SCAN_TABLES 是否加专门成功表(Pss 加 Pss/PssLoop;Ani 加 Ani/AniMask)、有无 AUDIO_TABLES、报告标题文案。

---

## 6. 新建第 N 个技能的流程（用本框架）

拿到新文件类型 `.foo`:

1. **读两侧源码**(复刻 `src/Foo/Foo.cpp::ReadFile` + 引擎 `<Engine>::LoadFromFile`),按 §3 六槽位的判别式定填法。
2. **实测确认**:扩展名大小写(`find -iname`)、文件数 + 目录(`--dry-run`)、依赖类型分布(跑一次扫描看 Result)。
3. **套模板**:复制最接近的技能目录(无音频+路径→krl/SRScene/State;有音频→tani/kmsc;抽数值→Ani),按 §1 九节结构改槽位节,固定节直接保留(只改路径/ext 局部变量)。
4. **三脚本**:改 `_DEFAULT_ROOT` 子目录 + `--ext` 默认;diff/gen_report 改扩展名 + 表集。
5. **补 `建立软连接.cmd`**:加 `call :MakePathLink <技能名>` 行(**GBK+CRLF 感知**,Python 改时保持 CRLF,否则 cmd 粘连跳行)。
6. **验证**:3 脚本 `py_compile` + `--help` + 真实 db 自比 exit 0;零硬编码(`grep sword3-products/D:\JX3` 应 0);`regen` env 未设 exit 2。
7. **建软链 + 全链路测试**:跑 `建立软连接.cmd` → 技能进可用列表 → 走完整 §7 闭环(§8 汇报)。

---

## 7. 跨技能通用口径（写进每个 SKILL §2 的共性条款）

1. **§2 必有版本分支层**:版本标识数字(新>老)遍布解析全程,引擎新版本加分支/字段复刻没跟就错位漏抽;grep 版本号核分支上限。
2. **字节布局 vs 运行时默认**:改变字节数的分支要对齐;只改运行时变量值的分支复刻 SkipData 跳过即可。
3. **SkipData 折叠对齐**:复刻只抽需要的信息,跳过字段折叠进大 SkipData;比总字节数相等,不比逐字段读取方式。
4. **"缺 case" ≠ "必须同步"**:先核实是否真序列化进文件(引擎有 reader+SaveToFile),编辑器-only/不写盘的不同步。
5. **不改引擎**:引擎文件只读对标,绝不修改。
6. **资源对错解析时报,diff 不判**:复刻解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报资源对错,diff 只列差异、不判好坏(除有数值表可判)。

---

## 8. 框架自检清单（写完一个新技能,用此核对）

- [ ] §1 六项前置 + REPO gotcha 在(固定)
- [ ] §2 有版本分支层 + 结构层 + 字节布局/运行时默认区分(槽位 2)
- [ ] §3 抽取类数正确(无的类没照搬,槽位 3)
- [ ] §4 RUST 前置 + FileParse.sln(固定)
- [ ] §5 扫描目录/ext 正确 + 大小写说明 + 音频节有/无正确(槽位 4)
- [ ] §6 diff 风格 + 音频对比 有/无正确(槽位 5)
- [ ] §7 七步闭环在(固定)
- [ ] §8 五项汇报在(固定)
- [ ] §9 报告名 + 表集 + 脚本>>分工(槽位 6)
- [ ] 速查块 命令 =1 / REPO gotcha / RUST 前置 在
- [ ] 三脚本:零硬编码、env 未设 exit 2、ext 大小写不敏感
- [ ] `建立软连接.cmd` 补了行(GBK+CRLF)
- [ ] 全链路测试通过(软链→脚本→真实数据 exit 0)

---

## 9. 文档分工

| 文档 | 定位 | 何时读 |
|---|---|---|
| **CodeReviewFrame.md(本文)** | 骨架结构 + 槽位定义 + 判别式(抽象,无具体技能值) | 新建技能定结构时 |
| **CodeReview.md** | 7 技能横向对比 + 新建配方(有具体值/矩阵) | 新建技能查同类填法、回看异同时 |
| **CodeReview\<Ext>.md** | 单技能规范(用户写的,列与 Pss 异同点) | 写该技能前(§2 留空要我总结) |
| **\<技能>\SKILL.md** | 技能本体(可执行) | 跑技能时 |
| **记忆 project_\<x>_sync_skill** | 单技能位置/差异/实测(跨会话持久) | 接续该技能时 |
| **记忆 feedback_*** | 踩坑/口径(跨技能通用) | 跑任何技能前 |

> 本框架从 7 个已建技能抽象而来,已验证可复用(第 2-7 个技能都是按此骨架生成的)。加新技能时:本文定结构 → `CodeReview.md` 查填法 → `CodeReview<Ext>.md` 看该技能规范 → 套模板 → §8 自检清单核对。
