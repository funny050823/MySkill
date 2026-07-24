#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_krl.py — 纯差异工具:对比两次全量 krl 扫描,列出修改前后数据差异(失败集+依赖路径)。

用途: krl代码同步技能里,改复刻代码前跑一次全量得 baseline,改+编译后再跑一次得 current,
      用本脚本列出差异(哪些 krl 的失败/依赖变了)。

重要: 本脚本只报"差异",不判断差异算回归还是改善——好坏由报告/Claude 人工裁定(同 kmsc/Ani/tani 方案)。
      资源对错是 KRL.cpp 解析时 OnErrorByGBK/OnReadResourceFileByGBK 报的职责,不是 diff 的职责。

数据来源(ScanResult.db,krl 无音频、无专门成功表,同 kmsc/Ani):
  (a) 解析失败: Result 中 File 以 .krl 结尾 且 ErrLevel=7
  (b) 依赖路径: Result 中 File 以 .krl 结尾 的 (SonFile,SonExtName,ErrLevel,ErrType) 集合,按 krl 分组

差异类别(中性,不判好坏):
  changed        : 两侧都解析成功,但失败/依赖集变了
  appeared       : current 新进(baseline 失败/未扫到)——如修复版本外漏抽(新版本 .krl 从 default 报错变抽到依赖)
  disappeared    : baseline 有、current 不在了(现在失败/未扫到)——需关注,可能回归
  still_failing  : 两侧都失败。与 --knownbad 交集 = 预期坏文件;其余待人工裁定
  new_fail       : baseline 没扫到、current 却失败(同清单下一般不出现,出现即异常)
  stable         : 两侧都成功且依赖集完全相同

无音频对比(krl 没有音频标签,不跑 SearchAudioLabel,无 --audiolabel)。

用法:
  python diff_krl.py <baseline ScanResult.db> <current ScanResult.db> [--knownbad FILE] [--json] [--quiet]

退出码: 0 正常(差异已列,好坏人工裁定); 1 异常(new_fail 非空); 2 输入异常。
         差异本身不导致 exit1——diff 是纯差异工具,不替你判回归。
"""
import argparse
import json
import os
import sqlite3
import sys


def norm(s):
    if s is None:
        return ""
    return s.strip().lower().replace("/", "\\")


def is_krl(f):
    return f.endswith(".krl")


def connect(db):
    if not os.path.isfile(db):
        raise RuntimeError("db 不存在: %s" % db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def read_krl_result(db):
    """读 Result 表里所有 File 以 .krl 结尾的记录。
    返回:
      failed  : set(norm(File)) 中 ErrLevel=7 的
      depend  : { norm(File): set( (norm(SonFile), norm(SonExtName), ErrLevel, ErrType) ) }
      scanned : set(norm(File))  (File 在 FileList 里的 krl,用于 sanity)
    """
    failed = set()
    depend = {}
    scanned = set()
    try:
        con = connect(db)
        # 解析失败 + 依赖(都在 Result,File 以 .krl 结尾)
        cur = con.execute(
            "SELECT File, SonFile, SonExtName, ErrLevel, ErrType FROM Result "
            "WHERE lower(File) LIKE '%.krl'")
        for r in cur.fetchall():
            f = norm(r["File"])
            if not is_krl(f):
                continue
            errlevel = r["ErrLevel"] if r["ErrLevel"] is not None else 0
            if errlevel == 7:
                failed.add(f)
            son = norm(r["SonFile"])
            sonext = norm(r["SonExtName"])
            depend.setdefault(f, set()).add((son, sonext, errlevel, r["ErrType"] if r["ErrType"] is not None else 0))
        # sanity: FileList 里的 krl
        try:
            cur = con.execute("SELECT File FROM FileList WHERE lower(File) LIKE '%.krl'")
            for r in cur.fetchall():
                scanned.add(norm(r["File"]))
        except sqlite3.Error:
            pass
        con.close()
    except sqlite3.Error as e:
        print("warn: 读取 Result 失败(%s): %s" % (db, e), file=sys.stderr)
    except RuntimeError as e:
        print("错误: %s" % e, file=sys.stderr)
        raise
    return failed, depend, scanned


def load_knownbad(path):
    if not path:
        return set()
    raw = open(path, "rb").read()
    text = None
    for enc in ("gbk", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        text = raw.decode("gbk", "replace")
    s = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            s.add(norm(line))
    return s


def main():
    ap = argparse.ArgumentParser(description="对比两份 krl ScanResult.db 的纯差异(失败集+依赖,无音频)")
    ap.add_argument("baseline", help="改码前 baseline ScanResult.db")
    ap.add_argument("current", help="改码后 current ScanResult.db")
    ap.add_argument("--knownbad", default=None, help="已知坏 krl 清单(每行一个路径)")
    ap.add_argument("--json", action="store_true", help="输出 machine-readable JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总计数")
    args = ap.parse_args()

    for db in (args.baseline, args.current):
        if not os.path.isfile(db):
            print("错误: db 不存在: %s" % db, file=sys.stderr)
            return 2

    kb = load_knownbad(args.knownbad)

    b_fail, b_dep, b_scan = read_krl_result(args.baseline)
    c_fail, c_dep, c_scan = read_krl_result(args.current)

    # 纯差异:只报差异,不判好坏(同 kmsc/Ani/tani 方案)
    all_files = set(b_fail) | set(c_fail) | set(b_dep) | set(c_dep) | b_scan | c_scan

    changed = []      # 两侧都解析成功,但依赖集变了(中性)
    appeared = []      # current 新进(baseline 失败/未扫到)——如修复漏抽/版本外
    disappeared = []   # baseline 有、current 不在了(现在失败/未扫到)——需关注
    still_failing = [] # 两侧都失败
    new_fail = []      # baseline 没扫到、current 失败(异常)
    stable = 0         # 两侧都成功且依赖集不变

    for f in all_files:
        bf = f in b_fail
        cf = f in c_fail
        bd = b_dep.get(f, set())
        cd = c_dep.get(f, set())

        if bf and not cf:
            appeared.append({"file": f, "from": "failed", "to": "parsed"})
            continue
        if cf and not bf:
            new_fail.append({"file": f, "from": "absent" if f not in b_scan else "parsed", "to": "failed"})
            continue
        if bf and cf:
            still_failing.append({"file": f})
            continue
        # 都不失败:比依赖集(中性,不判好坏)
        if bd != cd:
            changed.append({"file": f, "from": "%d deps" % len(bd), "to": "%d deps" % len(cd)})
        else:
            stable += 1

    still_knownbad = [x for x in still_failing if x["file"] in kb]
    still_unknown = [x for x in still_failing if x["file"] not in kb]

    c_counts = {
        "baseline_failed": len(b_fail),
        "current_failed": len(c_fail),
        "baseline_scanned": len(b_scan),
        "current_scanned": len(c_scan),
        "baseline_depend_records": sum(len(v) for v in b_dep.values()),
        "current_depend_records": sum(len(v) for v in c_dep.values()),
        "stable": stable,
        "changed": len(changed),
        "appeared": len(appeared),
        "disappeared": len(disappeared),
        "still_failing": len(still_failing),
        "still_failing_knownbad": len(still_knownbad),
        "still_failing_unknown": len(still_unknown),
        "new_fail": len(new_fail),
    }
    result = {
        "baseline": args.baseline,
        "current": args.current,
        "counts": c_counts,
        "changed": changed,
        "appeared": appeared,
        "disappeared": disappeared,
        "still_failing_knownbad": still_knownbad,
        "still_failing_unknown": still_unknown,
        "new_fail": new_fail,
    }

    hf = sys.stderr if args.json else sys.stdout
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.quiet:
        print("baseline: failed=%d scanned=%d depend_recs=%d" %
              (c_counts["baseline_failed"], c_counts["baseline_scanned"], c_counts["baseline_depend_records"]), file=hf)
        print("current : failed=%d scanned=%d depend_recs=%d" %
              (c_counts["current_failed"], c_counts["current_scanned"], c_counts["current_depend_records"]), file=hf)
        print("stable=%d  changed=%d  appeared=%d  disappeared=%d  still_failing=%d(kb=%d unknown=%d)  new_fail=%d" %
              (c_counts["stable"], c_counts["changed"], c_counts["appeared"], c_counts["disappeared"],
               c_counts["still_failing"], c_counts["still_failing_knownbad"], c_counts["still_failing_unknown"],
               c_counts["new_fail"]), file=hf)
        if changed:
            print("\n[差异-依赖集变化] 以下 krl 两侧都解析但依赖集变了(好坏人工裁定):", file=hf)
            for x in changed[:20]:
                print("  %s  (%s -> %s)" % (x["file"], x["from"], x["to"]), file=hf)
            if len(changed) > 20:
                print("  ... 另有 %d 条" % (len(changed) - 20), file=hf)
        if appeared:
            print("\n[差异-新进] 以下 krl baseline 失败/未抽到、current 抽到依赖(如修复版本外漏抽):", file=hf)
            for x in appeared[:20]:
                print("  %s" % x["file"], file=hf)
            if len(appeared) > 20:
                print("  ... 另有 %d 条" % (len(appeared) - 20), file=hf)
        if disappeared:
            print("\n[差异-消失] 以下 krl baseline 有、current 不在了(需关注):", file=hf)
            for x in disappeared[:20]:
                print("  %s" % x["file"], file=hf)
        if still_unknown:
            print("\n[仍失败-未归类] 需人工裁定(真坏文件 vs 复刻仍落后):", file=hf)
            for x in still_unknown[:20]:
                print("  %s" % x["file"], file=hf)

    # 纯差异工具:差异本身不=失败;只有 new_fail(异常)才 exit1
    has_anomaly = bool(new_fail)
    verdict = "ANOMALY(new_fail)" if has_anomaly else "OK(差异已列,好坏人工裁定)"
    print("\n结论: %s" % verdict, file=hf)
    return 1 if has_anomaly else 0


if __name__ == "__main__":
    sys.exit(main())
