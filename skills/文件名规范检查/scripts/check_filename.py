#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_filename.py — 文件名规范检查(技能「文件名规范检查」)

深度检索 --root(默认 $JX3_HD_Client) 下所有文件名与目录名,逐字符检测是否能用 GBK(cp936) 编码,
列出含非 GBK 字符的文件/目录并**标注是哪个字符**(位置 + 字符 + Unicode 码点 + UTF-8 字节),
生成 markdown 报告到 --out-dir 下 CheckFileName<YYMMDD_HHMMSS>.md(UTF-8)。

判定标准:Python 的 'gbk' codec 能否编码该字符。encode 失败 = 非 GBK。
  - GBK 是 GB2312 超集;Python 'gbk' 覆盖 GBK 全集。ASCII 与常用中文均在 GBK 内,不会误报。
  - emoji、特殊符号(如 ☼ U+263C)、部分生僻字/扩展字符不在 GBK 内,会被检出。

性能:先对整名 name.encode('gbk') 一次快速过滤(绝大多数文件名纯 ASCII/GBK,一次过),
  失败才逐字符定位。几十万文件数十秒内完成。

路径不写死(换台机器可跑):
  - --root 默认取环境变量 JX3_HD_Client;
  - --out-dir 由 SKILL.md 传 $REPO/Docs(REPO = `pwd -W` 取项目根)。
  只要环境变量与项目在,技能即可跑,不依赖写死的本机绝对路径。

用法:
  python check_filename.py --root <目录> --out-dir <报告目录>
       [--skip-dirs .svn,.git] [--name CheckFileName] [--no-dirs] [--limit N]

退出码: 0 成功(无论是否发现非GBK); 1 异常; 2 未设 JX3_HD_Client 且未传 --root,或 --root 不存在。
"""
import argparse
import os
import sys
import datetime


def is_gbk(s):
    """整名能否用 GBK 编码(快速过滤用)。"""
    try:
        s.encode("gbk")
        return True
    except UnicodeEncodeError:
        return False


def non_gbk_chars(name):
    """逐字符定位,返回 [(index, char, ord), ...]。仅在整名 is_gbk 为 False 时调用。"""
    bad = []
    for i, ch in enumerate(name):
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            bad.append((i, ch, ord(ch)))
    return bad


def annotate(name, bad_idx_set):
    """把非 GBK 字符在名字里替换为 [U+XXXX],生成标注名,直观看位置。"""
    out = []
    for i, ch in enumerate(name):
        if i in bad_idx_set:
            out.append("[U+%04X]" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def utf8_hex(ch):
    return " ".join("%02X" % b for b in ch.encode("utf-8"))


def walk_and_scan(root, skip_dirs, scan_dirs=True, scan_files=True, limit=None):
    """递归扫描 root。返回 (bad_files, bad_dirs, total_files, total_dirs, errors)。
    bad_files/bad_dirs 元素:(abs_path, name, [(idx, char, ord), ...])
    """
    bad_files = []
    bad_dirs = []
    total_files = 0
    total_dirs = 0
    errors = []
    skip_set = set(skip_dirs)
    tick = 0

    def onerror(e):
        errors.append(str(e))

    for dirpath, dirs, files in os.walk(root, onerror=onerror):
        # 原地过滤:不进 .svn/.git 等版本库/元数据目录
        if skip_set:
            dirs[:] = [d for d in dirs if d not in skip_set]
        if scan_dirs:
            for d in dirs:
                total_dirs += 1
                if not is_gbk(d):
                    bad_dirs.append((os.path.abspath(os.path.join(dirpath, d)), d, non_gbk_chars(d)))
        if scan_files:
            for f in files:
                total_files += 1
                if not is_gbk(f):
                    bad_files.append((os.path.abspath(os.path.join(dirpath, f)), f, non_gbk_chars(f)))
        tick += 1
        if tick % 5000 == 0:
            print("progress: files=%d dirs=%d bad_files=%d bad_dirs=%d"
                  % (total_files, total_dirs, len(bad_files), len(bad_dirs)), file=sys.stderr)
        if limit and (total_files + total_dirs) >= limit:
            break
    return bad_files, bad_dirs, total_files, total_dirs, errors


def build_char_stat(bad_files, bad_dirs):
    """聚合非 GBK 字符统计:ord -> {ch, count, files:set, dirs:set, samples:[path]}"""
    stat = {}

    def feed(path, bad, kind):
        for _idx, ch, o in bad:
            e = stat.get(o)
            if e is None:
                e = {"ch": ch, "count": 0, "files": set(), "dirs": set(), "samples": []}
                stat[o] = e
            e["count"] += 1
            if kind == "file":
                e["files"].add(path)
            else:
                e["dirs"].add(path)
            if len(e["samples"]) < 3:
                e["samples"].append(path)

    for ap, _name, bad in bad_files:
        feed(ap, bad, "file")
    for ap, _name, bad in bad_dirs:
        feed(ap, bad, "dir")
    return stat


def md_escape_path(p):
    """Windows 反斜杠路径,用反引号代码块包(代码内反斜杠不转义)。返回 `path`。"""
    # 规范成反斜杠(abspath 在 Windows 已是反斜杠,但防御性处理)
    p = p.replace("/", "\\")
    return "`%s`" % p


def build_report(root, bad_files, bad_dirs, total_files, total_dirs,
                 skip_dirs, errors, ts_full, ts_short):
    lines = []
    lines.append("# 文件名规范检查报告")
    lines.append("")
    lines.append("> 深度检索路径下所有文件名/目录名,逐字符检测 GBK(cp936)可编码性,列出含非 GBK 字符者并标注是哪个字符。")
    lines.append("")
    lines.append("- **扫描根**:%s" % md_escape_path(os.path.abspath(root)))
    lines.append("- **生成时间**:%s" % ts_full)
    lines.append("- **报告文件**:`CheckFileName%s.md`" % ts_short)
    lines.append("- **判定标准**:`ch.encode('gbk')` 失败即非 GBK(GBK 含 ASCII 与常用中文,不会误报;emoji/特殊符号/部分生僻字会检出)")
    lines.append("- **跳过的目录名**:%s(版本库/元数据,不扫)" % (", ".join(skip_dirs) if skip_dirs else "(无)"))
    lines.append("")

    n_bad_files = len(bad_files)
    n_bad_dirs = len(bad_dirs)
    stat = build_char_stat(bad_files, bad_dirs)
    total_char_occ = sum(e["count"] for e in stat.values())

    lines.append("## 一、扫描概览")
    lines.append("")
    lines.append("| 项目 | 数量 |")
    lines.append("|---|---|")
    lines.append("| 扫描总文件数 | %d |" % total_files)
    lines.append("| 扫描总目录数 | %d |" % total_dirs)
    lines.append("| 含非 GBK 字符的文件数 | **%d** |" % n_bad_files)
    lines.append("| 含非 GBK 字符的目录数 | **%d** |" % n_bad_dirs)
    lines.append("| 非 GBK 字符种类 | %d |" % len(stat))
    lines.append("| 非 GBK 字符出现总次数 | %d |" % total_char_occ)
    lines.append("| 遍历错误次数 | %d |" % len(errors))
    lines.append("")
    if n_bad_files == 0 and n_bad_dirs == 0:
        lines.append("**结论**:扫描范围内所有文件名与目录名均为 GBK 可编码,**未发现不规范字符**。")
        lines.append("")
    else:
        lines.append("**结论**:发现 **%d 个文件 + %d 个目录** 含非 GBK 字符,详见下表。**标注文件名**列把非 GBK 字符就地替换为 `[U+XXXX]`,一眼可见是哪个字符、在名字哪个位置。" % (n_bad_files, n_bad_dirs))
        lines.append("")

    # 二、字符汇总
    if stat:
        lines.append("## 二、非 GBK 字符汇总(按出现次数降序)")
        lines.append("")
        lines.append("| 字符 | 码点 | UTF-8 字节 | 出现次数 | 涉及文件数 | 涉及目录数 | 样本路径(前 3) |")
        lines.append("|---|---|---|---|---|---|---|")
        for o, e in sorted(stat.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
            ch = e["ch"]
            samples = "; ".join(md_escape_path(p) for p in e["samples"])
            # 字符可能在 GBK 终端不可见,但同时给码点(权威)
            lines.append("| %s | U+%04X | %s | %d | %d | %d | %s |"
                        % (ch, o, utf8_hex(ch), e["count"], len(e["files"]), len(e["dirs"]), samples))
        lines.append("")

    # 三、文件清单
    if bad_files:
        lines.append("## 三、含非 GBK 字符的文件清单(%d 个)" % n_bad_files)
        lines.append("")
        lines.append("> 格式:全路径 + 原文件名 + 标注文件名(非 GBK 字符就地标 `[U+XXXX]`)+ 逐字符表(位置/字符/码点/UTF-8)。")
        lines.append("")
        for i, (ap, name, bad) in enumerate(bad_files, 1):
            bad_idx = {idx for idx, _ch, _o in bad}
            lines.append("### %d. %s" % (i, md_escape_path(ap)))
            lines.append("")
            lines.append("- 原文件名:`%s`" % name)
            lines.append("- 标注文件名:`%s`" % annotate(name, bad_idx))
            lines.append("- 非 GBK 字符(%d 个):" % len(bad))
            lines.append("")
            lines.append("| # | 位置 | 字符 | 码点 | UTF-8 字节 |")
            lines.append("|---|------|------|------|-----------|")
            for j, (idx, ch, o) in enumerate(bad, 1):
                lines.append("| %d | 第 %d 个 | %s | U+%04X | %s |"
                             % (j, idx + 1, ch, o, utf8_hex(ch)))
            lines.append("")

    # 四、目录清单
    if bad_dirs:
        lines.append("## 四、含非 GBK 字符的目录清单(%d 个)" % n_bad_dirs)
        lines.append("")
        lines.append("> 目录名含非 GBK 字符会影响其下所有文件的完整路径,需一并整改。")
        lines.append("")
        for i, (ap, name, bad) in enumerate(bad_dirs, 1):
            bad_idx = {idx for idx, _ch, _o in bad}
            lines.append("### %d. %s" % (i, md_escape_path(ap)))
            lines.append("")
            lines.append("- 原目录名:`%s`" % name)
            lines.append("- 标注目录名:`%s`" % annotate(name, bad_idx))
            lines.append("- 非 GBK 字符(%d 个):" % len(bad))
            lines.append("")
            lines.append("| # | 位置 | 字符 | 码点 | UTF-8 字节 |")
            lines.append("|---|------|------|------|-----------|")
            for j, (idx, ch, o) in enumerate(bad, 1):
                lines.append("| %d | 第 %d 个 | %s | U+%04X | %s |"
                             % (j, idx + 1, ch, o, utf8_hex(ch)))
            lines.append("")

    # 五、遍历错误
    if errors:
        lines.append("## 五、遍历错误(%d 次,已跳过)")
        lines.append("")
        lines.append("```")
        for e in errors[:50]:
            lines.append(e)
        if len(errors) > 50:
            lines.append("... (仅显示前 50 条)")
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("*报告由技能「文件名规范检查」生成,脚本 `check_filename.py`。*")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="文件名规范检查:深度检索并找出含非 GBK 字符的文件名/目录名")
    ap.add_argument("--root", default=os.environ.get("JX3_HD_Client"),
                    help="扫描根目录(默认取环境变量 JX3_HD_Client;env 未设须显式传)")
    ap.add_argument("--out-dir", default=".",
                    help="报告输出目录(脚本在其下生成 CheckFileName<YYMMDD_HHMMSS>.md;SKILL.md 传 $REPO/Docs)")
    ap.add_argument("--skip-dirs", default=".svn,.git",
                    help="跳过的目录名,逗号分隔(默认 .svn,.git)")
    ap.add_argument("--name", default="CheckFileName",
                    help="报告文件名前缀(默认 CheckFileName)")
    ap.add_argument("--no-dirs", action="store_true",
                    help="只查文件名,不查目录名(默认文件名+目录名都查)")
    ap.add_argument("--limit", type=int, default=None,
                    help="调试用:扫描条目上限(文件+目录)")
    args = ap.parse_args()

    if not args.root:
        print("错误:未设环境变量 JX3_HD_Client 且未传 --root,技能终止。", file=sys.stderr)
        return 2
    if not os.path.isdir(args.root):
        print("错误:--root 不是目录:%s" % args.root, file=sys.stderr)
        return 2

    skip_dirs = [s.strip() for s in args.skip_dirs.split(",") if s.strip()]
    scan_dirs = not args.no_dirs

    print("扫描根: %s" % args.root, file=sys.stderr)
    print("跳过目录: %s" % (", ".join(skip_dirs) if skip_dirs else "(无)"), file=sys.stderr)
    print("检查目录名: %s" % ("否" if args.no_dirs else "是"), file=sys.stderr)

    bad_files, bad_dirs, total_files, total_dirs, errors = walk_and_scan(
        args.root, skip_dirs, scan_dirs=scan_dirs, scan_files=True, limit=args.limit)

    ts_full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts_short = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
    # 时间戳用扫描完成时刻;两段分别取会差几微秒,为保文件名与报告内时间一致,统一用 ts_short 派生
    ts_full = datetime.datetime.strptime(ts_short, "%y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "%s%s.md" % (args.name, ts_short))

    report = build_report(args.root, bad_files, bad_dirs, total_files, total_dirs,
                          skip_dirs, errors, ts_full, ts_short)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report)

    # ASCII 汇总行:任何控制台编码下 Claude 都能稳定解析
    print("RESULT status=ok report=%s files=%d dirs=%d badfiles=%d baddirs=%d badchars=%d charocc=%d errors=%d"
          % (out_path, total_files, total_dirs, len(bad_files), len(bad_dirs),
             len(build_char_stat(bad_files, bad_dirs)), sum(len(b[2]) for b in bad_files) + sum(len(b[2]) for b in bad_dirs),
             len(errors)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
