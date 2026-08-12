---
name: 文件名规范检查
description: 深度检索 JX3 客户端目录($JX3_HD_Client)下所有文件名与目录名,逐字符检测是否能用 GBK(cp936)编码,列出含非 GBK 字符的文件/目录并**重点标注是哪个字符**(字符本身 + Unicode 码点 U+XXXX + UTF-8 字节 + 在名字中的位置),生成 markdown 报告到项目 Docs/CheckFileNameYYMMDD_HHMMSS.md。当用户提到 文件名规范检查、文件名非 GBK、文件名含非 GBK 字符、文件名乱码、检查文件名编码、检查目录名编码、JX3 客户端文件名不规范、找出文件名/目录名里的特殊字符或 emoji、或想排查客户端目录下哪些文件名/目录名不能用 GBK 编码时,务必使用本技能。它递归扫描整个 client 目录,自动生成带时间戳的报告,无需改码、无闭环。
---

# 文件名规范检查（深度检索 + 非 GBK 字符定位）

## 为什么有这个技能

JX3 客户端目录(`$JX3_HD_Client` = `d:\JX3\trunk\sword3-products\trunk\client\`)以 GB 计,文件名/目录名里偶有混入**非 GBK 字符**(emoji、特殊符号如 `☼` U+263C、部分生僻字/扩展字符)。这些名字在 GBK 工具链(`setlocale(".936")`、`fopen` 按字节)下会乱码或读不到,是资源扫描/打包/路径登记的隐患。本技能**深度递归检索整个 client 目录**,逐字符判定 GBK 可编码性,把含非 GBK 字符的文件名/目录名**逐个列出并标注是哪个字符**,产出带时间戳的 markdown 报告供人工整改。

> 判定标准:Python `ch.encode('gbk')` 失败 = 非 GBK。GBK 含 ASCII 与常用中文,不会误报;emoji/特殊符号/部分扩展字符会被检出。
> 工作模式:**一次性扫描 + 生成报告**(无改码、无闭环、无编译)。仅 Windows 下执行。

---

## 1. 前置环境（进技能第一步先核实）

| 环境变量 | 必需 | 用途 | 缺失后果 |
|---|---|---|---|
| `JX3_HD_Client` | **必** | 被检索的 client 根目录(扫描输入),指向 sword3-products 下的 client 副本,内容以 GB 计、不会为空 | 脚本报"未设 JX3_HD_Client 且未传 --root"并 exit 2 |

检查命令(bash):
```bash
[ -n "$JX3_HD_Client" ] && [ -d "$JX3_HD_Client" ] && echo "JX3_HD_Client OK: $JX3_HD_Client" || echo "缺失/无效,技能终止"
```
任一不满足 → 报错并停止(脚本自身也会再校验一次)。

> **项目路径(仓库根)**:`KResourceReader` 仓库根 = Claude 执行技能时的工作目录(Primary working directory)。bash 命令块用 `REPO="$(pwd -W)"`(Windows 绝对)。Claude 执行技能 cwd 本就在仓库根,`pwd -W` 直接对(勿在子目录里 `cd .. && pwd -W`,会多一层)。

> **路径不写死(换台机器可跑)**:检索根用环境变量 `$JX3_HD_Client`,报告目录用 `REPO="$(pwd -W)"` 动态取项目根再拼 `Docs`。脚本内**无任何写死的本机绝对路径**,换台机器只要 `JX3_HD_Client` 环境变量与项目仓库在,技能即可跑。

---

## 2. 运行（核心命令,一行)

```bash
REPO="$(pwd -W)"  # 项目根(Windows 绝对);cwd 在仓库根时直接对
python "$REPO/.claude/skills/文件名规范检查/scripts/check_filename.py" \
  --root "$JX3_HD_Client" \
  --out-dir "$REPO/Docs"
```

- 默认**文件名 + 目录名都查**;加 `--no-dirs` 只查文件名。
- 默认跳过 `.svn`、`.git`(版本库/元数据,不扫);用 `--skip-dirs` 覆盖(逗号分隔)。
- 报告文件名:`CheckFileName<YYMMDD_HHMMSS>.md`(时间戳 = 扫描完成时刻,两位年),落在 `$REPO/Docs/` 下,即用户指定路径 `项目路径\Docs\CheckFileNameYYMMDD_HHMMSS.md`。
- 控制台最后打印一行 **ASCII 汇总**(任何控制台编码下 Claude 都能稳定解析):
  ```
  RESULT status=ok report=<报告绝对路径> files=<总文件> dirs=<总目录> badfiles=<非GBK文件> baddirs=<非GBK目录> badchars=<字符种类> charocc=<总出现次数> errors=<遍历错误>
  ```
  - stderr 的中文提示在 git-bash 可能乱码,**以 RESULT 行为准**;报告本身是 UTF-8,中文/特殊字符正常。
- 退出码:`0` 成功(无论是否发现非 GBK);`2` 未设 `JX3_HD_Client` 且未传 `--root` 或根不存在;`1` 异常。

### 2.1 可选:只扫某子目录 / 只查文件名
```bash
# 只扫某子目录(快速定位)
python "$REPO/.claude/skills/文件名规范检查/scripts/check_filename.py" \
  --root "$JX3_HD_Client/data" --out-dir "$REPO/Docs"

# 只查文件名不查目录名
python "$REPO/.claude/skills/文件名规范检查/scripts/check_filename.py" \
  --root "$JX3_HD_Client" --out-dir "$REPO/Docs" --no-dirs

# 调试:限制扫描条目数
python "$REPO/.claude/skills/文件名规范检查/scripts/check_filename.py" \
  --root "$JX3_HD_Client" --out-dir "$REPO/Docs" --limit 50000
```

---

## 3. 报告解读

报告 `CheckFileNameYYMMDD_HHMMSS.md`(UTF-8)结构:

1. **头部元信息**:扫描根、生成时间、报告文件名、判定标准、跳过的目录名。
2. **一、扫描概览**:总文件数、总目录数、含非 GBK 的文件/目录数、非 GBK 字符种类与出现总次数、遍历错误次数。结论一句话。
3. **二、非 GBK 字符汇总**(按出现次数降序):每个非 GBK 字符的 `字符 | 码点 | UTF-8 字节 | 出现次数 | 涉及文件数 | 涉及目录数 | 样本路径(前 3)`。**从这里一眼看到是哪些字符在作怪、各出现几次**。
4. **三、含非 GBK 字符的文件清单**:逐条:
   - 全路径(反引号包,反斜杠不转义)
   - 原文件名
   - **标注文件名**:非 GBK 字符就地替换为 `[U+XXXX]`,一眼可见是哪个字符、在名字哪个位置(例:`test_[U+263C]_file.txt`)
   - 逐字符表:`# | 位置(第几个) | 字符 | 码点 | UTF-8 字节`
5. **四、含非 GBK 字符的目录清单**:同上格式。目录名含非 GBK 会影响其下所有文件的完整路径,需一并整改。
6. **五、遍历错误**(若有):长路径/权限等原因跳过的条目(仅显示前 50 条)。

> "重点显示是哪个字符"的实现:每个含非 GBK 的文件/目录同时给出**字符本身 + Unicode 码点(权威)+ UTF-8 字节 + 在名字中的位置 + 标注文件名(就地标 `[U+XXXX]`)**。即便字符在 GBK 终端不可见,凭码点也能精确定位。

---

## 4. 注意事项

- **判定标准**:Python `'gbk'` codec。GBK 是 GB2312 超集,覆盖 ASCII + 常用中文 + GBK 扩展,常用中文名不会误报。emoji、特殊符号(☼ ★ 等)、部分 CJK 扩展/生僻字不在 GBK 内会被检出。如需更严格的 GB2312 判定,可在脚本里把 `'gbk'` 改 `'gb2312'`(但本项目口径是 GBK)。
- **文件名 vs 目录名**:默认都查。用户说"文件名"时,目录名同样影响路径完整性,建议一并查(报告分两节)。
- **跳过 `.svn`/`.git`**:版本库元数据不是用户资源,默认跳过;扫它们会混入大量无关英文/哈希名,无意义。用 `--skip-dirs ""` 可关闭(逗号分隔传空串需引号)。
- **性能**:先对整名 `name.encode('gbk')` 一次快速过滤(绝大多数文件名纯 ASCII/GBK,一次过),失败才逐字符定位。几十万文件数十秒内完成,每 5000 个目录打印一次进度到 stderr。
- **长路径/权限**:Windows 长路径(>260)或无权限目录会被 `os.walk` 的 `onerror` 捕获,记进报告"五、遍历错误"并跳过,不中断扫描。
- **不写死路径**:脚本无任何写死的本机绝对路径。检索根 = `$JX3_HD_Client`(env),报告目录 = `$REPO/Docs`(`REPO="$(pwd -W)"`)。换台机器只需环境变量与项目在。

---

## 5. 执行流程（按此执行)

```
0. 前置:  核实 $JX3_HD_Client 存在且是目录(§1);缺失 → 报错终止
A. 扫描:  cd 仓库根 → REPO="$(pwd -W)" → 跑 check_filename.py --root $JX3_HD_Client --out-dir $REPO/Docs(§2)
B. 看汇总:解析 RESULT 行(badfiles/baddirs/badchars/charocc);读报告"二、字符汇总"看主要非 GBK 字符
C. 汇报:  把扫描范围(总文件/目录数)、含非 GBK 的文件/目录数、主要非 GBK 字符(字符+码点+出现次数)、报告路径报给用户
```
> 无改码、无闭环、无编译。报告自动落 `$REPO/Docs/CheckFileName<时间戳>.md`,无需手动重命名。

---

## 8. 汇报格式（收尾时给用户)

1. 扫描范围:扫描根(`$JX3_HD_Client`)、总文件数、总目录数、耗时(看 RESULT 行 + 扫描起止)。
2. 结果:含非 GBK 字符的文件数、目录数、非 GBK 字符种类与总出现次数。
3. 主要非 GBK 字符:按出现次数列前几个(字符 + 码点 + 出现次数),让用户知道是哪类字符作怪。
4. 报告路径:`项目路径\Docs\CheckFileNameYYMMDD_HHMMSS.md`(完整绝对路径)。
5. 建议:若发现,提示用户报告"三/四"清单逐条整改(文件名/目录名改名成 GBK);若未发现,明确说"全部 GBK 可编码,无不规范字符"。

---

## 附:快速命令速查

```bash
# 仓库根:Claude 执行技能时 cwd 本就在仓库根,pwd -W 直接取。
REPO="$(pwd -W)"  # 项目路径=仓库根(Windows 绝对)

# 前置检查
[ -n "$JX3_HD_Client" ] && [ -d "$JX3_HD_Client" ] && echo OK || echo "缺失 JX3_HD_Client,技能终止"

# 全量扫描 client(文件名+目录名都查,跳过 .svn/.git),报告落 $REPO/Docs/CheckFileName<时间戳>.md
python "$REPO/.claude/skills/文件名规范检查/scripts/check_filename.py" \
  --root "$JX3_HD_Client" --out-dir "$REPO/Docs"

# 解析汇总(取 RESULT 行即可):badfiles/baddirs/badchars/charocc + report 路径
# 报告:UTF-8 markdown,用 Read 工具读 $REPO/Docs/CheckFileName<时间戳>.md
```
