# 代码同步技能框架

> 本框架从 7 个已建技能(Pss/kmsc/Ani/tani/krl/SRScene/State)抽象而来,描述一个"代码同步"技能由哪些环节组成、每环节是通用/均不同/细微差异、以及填什么。
>
> **环节 = 做一件事的流程步骤**(不是文档章节)。标注:
> - **(通用)** = 7 技能一字不差,直接套;
> - **(均不同)** = 每技能按文件类型自定,有判别式;
> - **(细微差异)** = 流程一样,只差几个参数(目录/ext/有无音频)。
>
> 配套:`CodeReviewFrame.md`(详细槽位+判别式)、`CodeReview.md`(7 技能对比矩阵)、`CodeReview<Ext>.md`(单技能规范)。

---

## 1. 执行环境检查（通用）

6 项,任一缺失报错终止,不继续:
- 4 环境变量:`JX3ENGINE_Sword3`(引擎源码根)/`JX3ENGINE_BASE`(编译 include)/`JX3ENGINE_DevEnv`/`JX3_HD_Client`(client 数据根)
- `MSBuildTool`(MSBuild.exe 路径)
- svn `wc.db`(`$JX3_HD_Client/../.svn/wc.db` 或 `$JX3_HD_Client/.svn/wc.db` 之一)

**已抽成通用可执行脚本(7 技能共享,维护 1 份)**:`_common/scripts/check_env.sh`
```bash
REPO="$(pwd -W)"  # 仓库根
bash "$REPO/.claude/skills/_common/scripts/check_env.sh" || exit 1
```
- 6 项任一缺失/无效 → 脚本 exit 1;全 OK exit 0,并 stdout 打印 `WCDB=<wc.db 路径>` 供后续复用(避免再判 `../.svn` vs `.svn`)。
- `_common` 经软链 `.claude/skills/_common` → `d:/StudyAndroid/MySkill/skills/_common`(无 SKILL.md,不被当技能加载,只是脚本仓库;`建立软连接.cmd` 已含 `_common` 行)。

---

## 2. 复刻函数与原函数（均不同）

- **复刻函数**:来自 `项目路径\src\<Ext>\<Ext>.cpp` 的 `<Ext>::ReadFile`(编进 `Jx3ResFileReaderAPI.vcxproj`)。详细定位:文件:行。
- **引擎原函数**:来自引擎 `<Engine>.cpp` 的 `<Engine>::LoadFromFile`(只读对标,不编不建)。详细定位:工程+文件:行。
- **调用路径**(判别):grep `AddFileType("<ext>"` 在 `Jx3ResFileReaderAPI.cpp`:
  - 找到 → reader 工厂路径(`AddFileType` → `ProcessXxx` → `new <Ext>` → `ReadFile`),大多数技能。
  - 找不到 → 查是否经 `Get<X>Info` 专用路径(`KResChecker→GetAniInfo→KBase::GetAniInfo→<Ext>::ScanFile→ReadFile`),目前仅 Ani。
- **复刻过程要提取的数据项**(= §3 抽取口径,见环节 4):grep 复刻的 `OnReadResourceFileByGBK`(路径)/`AddWwiseEvent`/`AddFmod`(音频)/数值成员落专门表(数值),定抽几类。
- **结构/枚举维护**:7 技能全是自维护副本(在复刻 `<Header>.h` 直接 `typedef struct`/`enum class`,非 `#include` 引擎头)。落后风险在枚举值/结构大小/switch case。⚠️ 引擎头本机未必能 Read,比对以引擎 `.cpp` 的 `Reference(sizeof)`/`_ReadBuffer`/字段访问反推字节数。

---

## 3. 差异比对（均不同,每轮第一步）

> 这是"改码前"的决策环节(每轮闭环都做),与环节 2 的"函数定位"(写技能时一次性)不同。

读两侧源码,定比对层(规范留空要我总结):
- 引擎怎么分派 → 定层:
  - 按**类型枚举** `switch(eType)` → 有"类型层"(grep 枚举两侧做 case 集合差)
  - 按**文件头 version** `switch(version)` → 有"版本层"(grep version 两侧做 case 集合差)
  - 按**per-item version** `if(dwVersion>=N)` → 有"per-item 版本分支层"(grep `>=N` 取两侧分支上限)
- **必含版本分支层**(普遍落后来源:新版本号>老,引擎新版本加字段,复刻没跟就错位/漏抽)
- **必含结构层**(grep 结构体名比字段/大小/pack)
- 列当轮待同步项,逐项核实是否真序列化进文件(引擎有 reader+SaveToFile 写入才算)。

**通用口径**(写进每技能 §2):
- 区分**字节布局分支**(改变读字节数,要对齐) vs **运行时默认分支**(只改运行时变量值,复刻 SkipData 跳过)——判定法:看是否改变 `Reference`/`SkipData`/`Read` 字节数。
- **SkipData 折叠对齐**:复刻只抽需要的信息,跳过字段折叠进大 SkipData;比**每段字节总数**相等,不比逐字段读取方式。
- **"switch 缺 case" ≠ "必须同步"**:先核实是否真序列化(编辑器-only/不写盘的不同步)。

---

## 4. 信息抽取（均不同,同步不变量必须守）

定抽几类(环节 2 的"提取数据项"细化):
| 信号 | 类 |
|---|---|
| `OnReadResourceFileByGBK(...)` 调用 | 明文依赖路径(落 ScanResult.db 的 Result 表) |
| `AddWwiseEvent`/`AddFmod` 调用 | 音频标签(落独立 AudioLabel.db 的 File 表,需跑 SearchAudioLabel) |
| 数值成员落专门表(如 PssInfo→Pss 表、BoneCnt→Ani 表) | 数值汇总(落专门成功表) |

组合:**三类**(路径+音频+数值=Pss)/ **两类**(路径+音频=kmsc/tani)/ **一类·数值**(Ani)/ **一类·路径**(krl/SRScene/State)。⚠️ 没有的类别照搬(如 krl 无数值汇总别抄 Pss §3.3)。

---

## 5. 编译代码（通用）

**已抽成通用可执行脚本(7 技能共享,维护 1 份)**:`_common/scripts/build.sh`
```bash
REPO="$(pwd -W)"  # 仓库根(先跑过 §1 check_env 保证 MSBuildTool/JX3ENGINE_Sword3 在)
bash "$REPO/.claude/skills/_common/scripts/build.sh" || exit 1
```
- 脚本先编 RUST 依赖(KESMBase/ClipLib,`FileParse.sln` 不含这两个工程不会自动先编),再 rebuild `FileParse.sln` 出 `Jx3SvnHookCheckTool.exe`。
- 设 `BUILD_SKIP_RUST=1` 跳过 RUST 前置(lib 已最新时省时间,默认编)。
- RUST lib 缺 → LNK1104 / 扫描时 `Jx3ResFileReaderAPI.dll` 加载 `GetLastError(126)`(dll 没拷到 OutDir)。
- 不用 `Build.cmd`(带 svn up/git 推送/PE 核验副作用)。
- LNK1104 → 查遗留 `Jx3*` 进程(`tasklist | grep Jx3` + `taskkill //PID //F`)或 RUST lib 没编。
- 判定:退出码 0 且 `x64\Release\Jx3SvnHookCheckTool.exe` 更新时间刷新即成功。

---

## 6. 构建测试环境（细微差异）

- **清单**:`ScanFileList_<ext>.txt` 必须 **GBK(cp936)+CRLF**,用 `_common/scripts/regen_scanlist.py` 生成(**7 技能共享 1 份,维护 1 份**;**别用 Edit/Write**,UTF-8 破坏中文):
  ```bash
  python "$REPO/.claude/skills/_common/scripts/regen_scanlist.py" \
    --root "$JX3_HD_Client/<子目录>" --ext <ext> \
    --out "$REPO/x64/Release/logs/ScanFileList_<ext>.txt"
  ```
- **差异点**(按文件类型填):
  - 扫描目录:`--root $JX3_HD_Client/<子目录>`(实测定,如 `data/source/other`/`data/movie`/`represent/rl`/`data/source/maps`…)。
  - 扩展名 + **大小写**:`--ext <ext>`,大小写不敏感(`.lower()` 比,匹配磁盘大写如 `.SRScene`)。注册名都小写,磁盘可能大写。
- `regen_scanlist.py` 默认根取自 `$JX3_HD_Client` 环境变量(**无硬编码兜底**,env 未设且不传 `--root` → exit 2)。各技能旧副本已删,统一用 `_common` 版。

---

## 7. 执行测试（细微差异）

```bash
ReadFileListFromSvnDB=1 bTest=1 ForDebug=0 ./Jx3SvnHookCheckTool.exe <client> <wc.db> <清单>
```
- `=1` 走 `CopyDataFromWCDBList`(清单 INNER JOIN svn wc.db 取元信息,再解析),**仍扫清单全量不漏文件**,FileList 多带 svn 元信息,多 ~8s。⚠️ 勿误以为 `=1` 是增量只扫改动(错)。
- **差异点**:
  - 有音频的技能(Pss/kmsc/tani):额外跑 `KSearchResource.exe SearchAudioLabel <client> <AudioLabel_<ext>_baseline/current.db>`,前后**不同 db 文件名**(InitDB 先删同名),跑完**保留禁删**。
  - 无音频的技能(Ani/krl/SRScene/State):不跑 SearchAudioLabel,无 AudioLabel.db。
- 工具 `setlocale(LC_ALL,".936")`,中文路径 OK。

---

## 8. 检查测试（细微差异）

- **检查测试数据正确性**(读报告):
  - 报告目录 `logs/JX3/trunk/<时间戳>/`,`Scan.log` 末尾应含"日志正常关闭"(没有=exe 执行失败)。
  - `ScanResult.db`:关注 `FileList`(扫到的文件集)/`Result`(失败 ErrLevel=7 + 依赖路径);**不关注 Pss 表**(Pss 技能自己关注 Pss 表)。有专门成功表的(Pss 的 Pss表/Ani 的 Ani表)还看它。
- **前后对比**(改码前后各跑一次,对比):
  - `diff_<ext>.py baseline vs current [--audiolabel ...]`(有音频加 `--audiolabel`)。
  - **差异点**:diff 风格——有专门成功表且字段变能判好坏 → **判断式**(`regressed`/`improved`/`audio_removed`,字段变=回归→exit1,Pss 这么用);无成功表/只抽路径 → **纯差异**(`changed`/`appeared`/`disappeared`/`still_failing`/`new_fail`,exit1 仅 `new_fail`,其余 6 个)。
  - 资源对错由复刻解析时 `OnErrorByGBK`/`OnReadResourceFileByGBK` 报,**diff 不判**(纯差异技能统一口径)。

---

## 9. 对比测试报告（落盘 UpdateCode<Ext>.md）

- 对比调整复刻函数前后,测试报告的差异,**说明差异原因**:
  - `gen_report_<ext>.py` `>>` 输出 md 片段(Scan.log 状态 + ScanResult 逐表对比 [+ AudioLabel 逐表对比,若有音频])。
  - Claude 在脚本片段**之上**补"一、本次代码改动""三、不同原因分析""四、终止结论"(脚本只给数字和样本,给不出改动说明和原因)。
- 报告 UTF-8(Edit/Write 安全,不是 GBK),覆盖式,一次改码任务一份。
- **只有真正改了代码才写报告**;已对齐没改码(健康基线)不写,只在对话说明。

---

## 贯穿全程的约束（不是环节,但每环节都要守）

### 闭环迭代（线性环节实为循环）
环节 3-9 是**循环**不是一次性:差异比对(3)→改码→编译(5)→测试(7)→检查对比(8)→有意外差异**回滚回 3** 重来,直到差异清零且无意外差异才终止。迭代上限 8 轮;编译错优先(不带着错测试);回滚要干净(改前 `cp` 备份复刻文件);**不改引擎**(只读对标)。

### 编码口径
- 源码 UTF-8:Edit/Write 安全。
- `ScanFileList_*.txt`、`.cmd`:GBK,**只用脚本/GBK 感知方式写**(Python `open(encoding='gbk')`),别用 Edit/Write。
- ⚠️ 改 GBK `.cmd` 保持 CRLF:Python 改时行尾写 `\r\n`,只写 `\n` 会让 cmd 粘连、跳行不执行(已踩)。

### 技能源维护口径
- **只维护 `d:\StudyAndroid\MySkill\skills\<技能>\`**(MySkill git 仓库源),不碰仓库内 `...\KResourceReader\.claude\skills\`。
- 仓库内 `.claude/skills/<技能>` 是 junction 软链 → MySkill,跑 `d:\StudyAndroid\MySkill\建立软连接.cmd` 建(GBK+CRLF)。
- ⚠️ Pss 仓库内是独立旧副本(真目录非软链),与 MySkill 未对齐——按既定保持现状,改 Pss 只改 MySkill 源。

### 脚本三件套(每技能 `scripts/`)
- `regen_scanlist.py`:通用共享,`--root`/`--ext`/`--out`/`--subset`/`--dry-run`,默认根取 `$JX3_HD_Client`(无硬编码兜底),ext 大小写不敏感,输出 GBK+CRLF。
- `diff_<ext>.py`:纯差异(或 Pss 判断式),`--knownbad`/`--audiolabel`(有音频)/`--json`/`--quiet`。
- `gen_report_<ext>.py`:逐表对比 ScanResult(FileList/Result,不关注 Pss)+ 可选 AudioLabel + 检查 Scan.log。
