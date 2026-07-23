#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_ani.py — 纯差异工具:对比两次全量 ani 扫描的 ScanResult.db,列出修改前后数据差异。

用途: Ani代码同步技能里,改复刻代码前跑一次全量得 baseline.db,改+编译后再跑一次
      得 current.db,用本脚本列出差异(哪些 ani 的 BoneCnt/VertexCnt/dwMask 变了)。

重要: 本脚本只报"差异",不判断差异算回归还是改善——好坏由报告/Claude 人工裁定。
      资源对错(如 VERVION3 BoneCnt==0)是 Ani.cpp 解析时 OnReadResourceFileByGBK 报异常的职责,不是 diff 的职责。

差异类别:
  changed        : 两侧都在 Ani 表,但 BoneCnt/VertexCnt/dwMask 变了(中性,不判好坏)
  appeared       : current 新进 Ani 表(baseline 不在:曾失败/未扫到)——如修复漏抽
  disappeared    : baseline 在 Ani 表、current 不在了(现在失败/未扫到)——需关注
  still_failing  : 两侧都失败(ErrLevel=7 且 .ani)。与 --knownbad 交集 = 预期坏文件;其余待人工裁定
  new_fail       : baseline 没扫到、current 却失败的(同清单下一般不出现,出现即异常)
  stable         : 两侧都在 Ani 表且字段完全相同

数据来源(ScanResult.db,Ani 技能只关注 Ani + Result,无 AudioLabel):
  Ani    : FilePath(主键),BoneCnt,VertexCnt,dwMask(=§3 的 m_dwNumBones/m_dwNumAnimatedVertices/m_dwMask;dwMask 列新版 exe 才有)
  Result : ErrLevel=7 且 File 以 .ani 结尾(或 ExtName=ani) = 解析失败
  (dwMask 仅当两侧 db 都有 dwMask 列时才参与比较;旧 exe 的 db 无 dwMask 列则只比 BoneCnt/VertexCnt)

用法:
  python diff_ani.py <baseline.db> <current.db> [--knownbad FILE] [--json] [--quiet]

退出码: 0 正常(差异已列出,好坏人工裁定); 1 异常(new_fail 非空); 2 输入异常。
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


def is_ani(f):
    return f.endswith(".ani")


def connect(db):
    if not os.path.isfile(db):
        raise RuntimeError("db 不存在: %s" % db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def read_ani(db):
    """读 Ani 表: {norm(FilePath): (BoneCnt, VertexCnt, Mask)}。
    Mask 列(新版 exe 产出的 Ani 表有,旧版无)若存在则读、纳入签名;不存在则该位置置 None。
    返回 (dict, has_mask_col)。表缺失返回 ({}, False)。"""
    out = {}
    has_mask = False
    try:
        con = connect(db)
        # 探测有无 Mask 列
        cols = [row[1] for row in con.execute("PRAGMA table_info(Ani)").fetchall()]
        has_mask = "dwMask" in cols
        if has_mask:
            cur = con.execute("SELECT FilePath, BoneCnt, VertexCnt, dwMask FROM Ani")
            for r in cur.fetchall():
                out[norm(r["FilePath"])] = (r["BoneCnt"] if r["BoneCnt"] is not None else 0,
                                             r["VertexCnt"] if r["VertexCnt"] is not None else 0,
                                             r["dwMask"])
        else:
            cur = con.execute("SELECT FilePath, BoneCnt, VertexCnt FROM Ani")
            for r in cur.fetchall():
                out[norm(r["FilePath"])] = (r["BoneCnt"] if r["BoneCnt"] is not None else 0,
                                             r["VertexCnt"] if r["VertexCnt"] is not None else 0,
                                             None)
        con.close()
    except sqlite3.Error as e:
        if "no such table" not in str(e):
            print("warn: 读取 Ani 失败(%s): %s" % (db, e), file=sys.stderr)
    except RuntimeError as e:
        print("错误: %s" % e, file=sys.stderr)
        raise
    return out, has_mask


def read_fail(db):
    """读 Result 中 ErrLevel=7 且 .ani 的失败集。"""
    out = set()
    try:
        con = connect(db)
        cur = con.execute(
            "SELECT DISTINCT File AS F FROM Result "
            "WHERE ErrLevel=7 AND (lower(File) LIKE '%.ani' OR lower(IFNULL(ExtName,''))='ani')")
        for r in cur.fetchall():
            out.add(norm(r["F"]))
        con.close()
    except sqlite3.Error as e:
        if "no such table" not in str(e):
            print("warn: 读取 Result(ani fail)失败(%s): %s" % (db, e), file=sys.stderr)
    return out


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
    ap = argparse.ArgumentParser(description="对比两份 ani ScanResult.db 的回归判据(Ani表+失败集)")
    ap.add_argument("baseline", help="改码前 baseline ScanResult.db")
    ap.add_argument("current", help="改码后 current ScanResult.db")
    ap.add_argument("--knownbad", default=None, help="已知坏 ani 清单(每行一个路径)")
    ap.add_argument("--json", action="store_true", help="输出 machine-readable JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总计数")
    args = ap.parse_args()

    for db in (args.baseline, args.current):
        if not os.path.isfile(db):
            print("错误: db 不存在: %s" % db, file=sys.stderr)
            return 2

    kb = load_knownbad(args.knownbad)

    b_ani, b_has_mask = read_ani(args.baseline)
    b_fail = read_fail(args.baseline)
    c_ani, c_has_mask = read_ani(args.current)
    c_fail = read_fail(args.current)
    # Mask 列仅当两侧 db 都有时才参与回归比较(旧 exe 的 db 无 Mask 列,跨版本比只看 BoneCnt/VertexCnt)
    cmp_mask = b_has_mask and c_has_mask

    all_files = set(b_ani) | set(c_ani) | b_fail | c_fail

    # 纯差异比较:只报修改前后数据差异,不判断差异算回归还是改善(好坏由报告/Claude 人工裁定)。
    # 资源对错(如 VERVION3 BoneCnt==0)是 Ani.cpp 解析时 OnReadResourceFileByGBK 报异常的职责,不是 diff 的职责。
    changed = []      # 两侧都在 Ani 表,但 BoneCnt/VertexCnt/dwMask 变了
    appeared = []      # current 新进 Ani 表(baseline 不在:失败/未扫到)
    disappeared = []   # baseline 在 Ani 表,current 不在了(现在失败/未扫到)
    still_failing = [] # 两侧都失败(ErrLevel=7 .ani)
    new_fail = []      # baseline 没扫到、current 失败
    stable = 0

    def sig(row):
        """差异签名:BoneCnt/VertexCnt 总比;dwMask 仅 cmp_mask 时纳入。"""
        bone, vert, mask = row
        return (bone, vert, mask) if cmp_mask else (bone, vert)

    for f in all_files:
        bp = f in b_ani
        cp = f in c_ani
        bf = f in b_fail
        cf = f in c_fail
        if bp:
            if not cp:
                disappeared.append({"file": f, "from": "parsed", "to": "failed" if cf else "absent"})
            else:
                # 两侧都在 Ani 表,比字段是否变化(不判好坏)
                if sig(b_ani[f]) != sig(c_ani[f]):
                    changed.append({"file": f, "from": "%s" % (sig(b_ani[f]),), "to": "%s" % (sig(c_ani[f]),)})
                else:
                    stable += 1
        else:
            # baseline 不在 Ani 表
            if cp:
                appeared.append({"file": f, "from": "failed" if bf else "absent", "to": "parsed"})
            elif cf:
                if bf:
                    still_failing.append({"file": f})
                else:
                    new_fail.append({"file": f, "from": "absent", "to": "failed"})

    still_knownbad = [x for x in still_failing if x["file"] in kb]
    still_unknown = [x for x in still_failing if x["file"] not in kb]

    c_counts = {
        "baseline_parsed": len(b_ani),
        "current_parsed": len(c_ani),
        "baseline_failed": len(b_fail),
        "current_failed": len(c_fail),
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
        print("baseline: parsed=%d failed=%d" % (c_counts["baseline_parsed"], c_counts["baseline_failed"]), file=hf)
        print("current : parsed=%d failed=%d" % (c_counts["current_parsed"], c_counts["current_failed"]), file=hf)
        print("stable=%d  changed=%d  appeared=%d  disappeared=%d  still_failing=%d(knownbad=%d unknown=%d)  new_fail=%d" %
              (c_counts["stable"], c_counts["changed"], c_counts["appeared"], c_counts["disappeared"],
               c_counts["still_failing"], c_counts["still_failing_knownbad"], c_counts["still_failing_unknown"],
               c_counts["new_fail"]), file=hf)
        if changed:
            print("\n[差异-字段变化] 以下 ani 的 BoneCnt/VertexCnt/dwMask 修改前后不同(好坏由人裁定,不自动判回归):", file=hf)
            for x in changed[:20]:
                print("  %s  (%s -> %s)" % (x["file"], x["from"], x["to"]), file=hf)
            if len(changed) > 20:
                print("  ... 另有 %d 条" % (len(changed) - 20), file=hf)
        if appeared:
            print("\n[差异-新进Ani表] 以下 ani baseline 不在 Ani 表、current 进了(如修复漏抽):", file=hf)
            for x in appeared[:20]:
                print("  %s  (%s -> parsed)" % (x["file"], x["from"]), file=hf)
            if len(appeared) > 20:
                print("  ... 另有 %d 条" % (len(appeared) - 20), file=hf)
        if disappeared:
            print("\n[差异-从Ani表消失] 以下 ani baseline 在 Ani 表、current 不在了(需关注):", file=hf)
            for x in disappeared[:20]:
                print("  %s  (%s -> %s)" % (x["file"], x["from"], x["to"]), file=hf)
            if len(disappeared) > 20:
                print("  ... 另有 %d 条" % (len(disappeared) - 20), file=hf)
        if still_unknown:
            print("\n[仍失败-未归类] 需人工裁定(真坏文件 vs 复刻仍落后):", file=hf)
            for x in still_unknown[:20]:
                print("  %s" % x["file"], file=hf)

    # 纯差异工具:差异本身不=失败;只有 new_fail(baseline 没扫到 current 却失败,异常)才 exit1
    has_anomaly = bool(new_fail)
    verdict = "ANOMALY(new_fail)" if has_anomaly else "OK(差异已列,好坏人工裁定)"
    print("\n结论: %s" % verdict, file=hf)
    return 1 if has_anomaly else 0


if __name__ == "__main__":
    sys.exit(main())
