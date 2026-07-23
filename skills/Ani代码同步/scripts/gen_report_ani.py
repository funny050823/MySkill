#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_report_ani.py — 为 UpdateCodeAni.md 生成"代码修改前后对比测试报告"的数据部分。

按 CodeReviewAni.md §6 要求,报告必须包含:
  1. Scan.log 最后一行是否有 "日志正常关闭"(没有=Jx3SvnHookCheckTool.exe 执行失败)
  2. ScanResult.db 逐表对比(FileList/Result/Ani 等)——相同/不同/原因
  (Ani 无音频,不比 AudioLabel.db)

本脚本只做机械逐表对比(相同/不同计数 + 不同样本),输出结构化数据。
"代码改动说明"和"不同原因"由 Claude 读本脚本输出 + 自记改动补写。

逐表对比法:取业务列(排除 ID 自增列)整行做元组,两 db 各一集合,比:
  same/only_baseline(丢失)/only_current(新增)/行数。不同 = only_b ∪ only_c。

用法:
  python gen_report_ani.py --baseline-scan <b ScanResult.db> --current-scan <c ScanResult.db>
       [--baseline-log <b Scan.log>] [--current-log <c Scan.log>] [--json]
  不带 --json 输出可直接粘进 md 的对比结果片段(UTF-8,stdout)。

退出码: 0 正常; 2 输入异常。
"""
import argparse
import json
import os
import sqlite3
import sys

# Ani 技能关注的 ScanResult.db 表(无 AudioLabel)。Ani 表 Mask 列新版 exe 才有,read_table 兼容缺失。
SCAN_TABLES = {
    "FileList": ["File", "ExtName", "translated_size", "changed_revision", "changed_date"],
    "Result": ["ErrType", "ErrLevel", "ResType", "File", "ExtName", "SonFile", "SonExtName", "Msg"],
    "Ani": ["FilePath", "BoneCnt", "VertexCnt", "Mask"],
}


def norm(s):
    if s is None:
        return ""
    return str(s).strip().lower().replace("/", "\\")


def read_table(db, table, cols):
    out = set()
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        # 探测表实际有哪些列,去掉不存在的(如 Ani.Mask 列旧版 exe 的 db 没有)
        actual = {row[1] for row in con.execute("PRAGMA table_info(%s)" % table).fetchall()}
        cols = [c for c in cols if c in actual]
        if not cols:
            con.close()
            return out
        col_sql = ",".join(cols)
        cur = con.execute("SELECT %s FROM %s" % (col_sql, table))
        for r in cur.fetchall():
            out.add(tuple(norm(r[c]) for c in cols))
        con.close()
    except sqlite3.Error as e:
        if "no such table" not in str(e):
            print("warn: 读取 %s.%s 失败: %s" % (db, table, e), file=sys.stderr)
    return out


def read_table_count(db, table):
    try:
        con = sqlite3.connect(db)
        n = con.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
        con.close()
        return n
    except sqlite3.Error:
        return None


def check_log(log_path):
    if not log_path or not os.path.isfile(log_path):
        return (False, False)
    try:
        with open(log_path, "rb") as f:
            data = f.read()
        text = None
        for enc in ("gbk", "utf-8-sig", "utf-8"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                pass
        if text is None:
            text = data.decode("gbk", "replace")
        lines = [l for l in text.splitlines() if l.strip()]
        last = lines[-1] if lines else ""
        return (True, "日志正常关闭" in last)
    except Exception as e:
        print("warn: 读 Scan.log 失败: %s" % e, file=sys.stderr)
        return (True, False)


def compare_table(table, cols, b_set, c_set, b_cnt, c_cnt):
    same = len(b_set & c_set)
    only_b = b_set - c_set
    only_c = c_set - b_set
    return {
        "table": table,
        "baseline_rows": b_cnt,
        "current_rows": c_cnt,
        "same": same,
        "only_baseline": len(only_b),
        "only_current": len(only_c),
        "different": len(only_b) + len(only_c),
        "only_baseline_samples": sorted(only_b)[:8],
        "only_current_samples": sorted(only_c)[:8],
    }


def main():
    ap = argparse.ArgumentParser(description="生成 UpdateCodeAni.md 的逐表对比数据(无音频)")
    ap.add_argument("--baseline-scan", required=True, help="改码前 ScanResult.db")
    ap.add_argument("--current-scan", required=True, help="改码后 ScanResult.db")
    ap.add_argument("--baseline-log", default=None, help="改码前报告目录 Scan.log")
    ap.add_argument("--current-log", default=None, help="改码后报告目录 Scan.log")
    ap.add_argument("--json", action="store_true", help="输出 JSON(供 Claude 汇总成 md)")
    args = ap.parse_args()

    for db in (args.baseline_scan, args.current_scan):
        if not os.path.isfile(db):
            print("错误: ScanResult.db 不存在: %s" % db, file=sys.stderr)
            return 2

    b_log = check_log(args.baseline_log)
    c_log = check_log(args.current_log)

    scan_cmp = []
    for t, cols in SCAN_TABLES.items():
        b = read_table(args.baseline_scan, t, cols)
        c = read_table(args.current_scan, t, cols)
        scan_cmp.append(compare_table(t, cols, b, c,
                                      read_table_count(args.baseline_scan, t),
                                      read_table_count(args.current_scan, t)))

    data = {
        "scan_log": {
            "baseline": {"exists": b_log[0], "has_close": b_log[1]},
            "current": {"exists": c_log[0], "has_close": c_log[1]},
        },
        "scanresult": scan_cmp,
    }

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("## 前后对比结果(脚本自动生成)\n")
    print("### Scan.log 进程状态")
    print("- baseline: " + ("存在,末尾含'日志正常关闭'" if b_log[1] else ("存在,末尾【无】'日志正常关闭'(进程可能失败)" if b_log[0] else "未提供/不存在")))
    print("- current : " + ("存在,末尾含'日志正常关闭'" if c_log[1] else ("存在,末尾【无】'日志正常关闭'(进程可能失败)" if c_log[0] else "未提供/不存在")))
    print()
    print("### ScanResult.db 逐表对比(Ani 技能关注 FileList/Result/Ani;无 AudioLabel)")
    print("| 表 | baseline行数 | current行数 | 相同 | baseline独有(丢失) | current独有(新增) | 不同合计 |")
    print("|---|---|---|---|---|---|---|")
    for t in scan_cmp:
        print("| `%s` | %s | %s | %d | %d | %d | %d |" %
              (t["table"], t["baseline_rows"], t["current_rows"], t["same"],
               t["only_baseline"], t["only_current"], t["different"]))
    print()
    for t in scan_cmp:
        if t["only_baseline_samples"]:
            print("- `%s` baseline 独有(current 丢失)前 %d:" % (t["table"], len(t["only_baseline_samples"])))
            for row in t["only_baseline_samples"]:
                print("    - %s" % " | ".join(row))
        if t["only_current_samples"]:
            print("- `%s` current 独有(新增)前 %d:" % (t["table"], len(t["only_current_samples"])))
            for row in t["only_current_samples"]:
                print("    - %s" % " | ".join(row))
    print()
    print("\n> 以上为脚本机械对比结果。**代码改动说明**与**不同原因分析**由 Claude 据本次改动补写于本节之上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
