#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_ani.py — 对比两次全量 ani 扫描的 ScanResult.db,给出"Ani 表 + 失败集"回归判据。

用途: Ani代码同步技能里,改复刻代码前跑一次全量得 baseline.db,改+编译后再跑一次
      得 current.db,用本脚本对比,判断本轮同步是否引入回归、目标文件是否改善。

判据(与 SKILL.md §6 一致;Ani 无音频):
  regressed(回归)  : baseline 在 Ani 表(曾解析 OK) -> current 不在 Ani(现在失败),
                     或在但 BoneCnt/VertexCnt/Mask 变了。非空 => 本轮不通过,回滚重来。
                     (Mask 仅当两侧 db 都有 Mask 列时才比;旧 exe 的 db 无 Mask 列则只看 BoneCnt/VertexCnt)
  improved(改善)   : baseline 解析失败 -> current 进了 Ani 表。本轮目标文件应在此。
  still_failing    : 两次都失败(ErrLevel=7 且 .ani)。与 --knownbad 交集 = 预期坏文件,不计回归;
                     其余 = 待人工裁定。
  new_fail         : baseline 没扫到、current 却失败的(同清单下一般不出现,出现即异常)。

数据来源(ScanResult.db,Ani 技能只关注 Ani + Result,无 AudioLabel):
  Ani    : FilePath(主键),BoneCnt,VertexCnt,Mask(=§3 的 m_dwNumBones/m_dwNumAnimatedVertices/m_dwMask;Mask 列新版 exe 才有)
  Result : ErrLevel=7 且 File 以 .ani 结尾(或 ExtName=ani) = 解析失败

用法:
  python diff_ani.py <baseline.db> <current.db> [--knownbad FILE] [--json] [--quiet]

退出码: 0 无回归; 1 有回归(regressed 或 new_fail 非空); 2 输入异常。
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
        has_mask = "Mask" in cols
        if has_mask:
            cur = con.execute("SELECT FilePath, BoneCnt, VertexCnt, Mask FROM Ani")
            for r in cur.fetchall():
                out[norm(r["FilePath"])] = (r["BoneCnt"] if r["BoneCnt"] is not None else 0,
                                             r["VertexCnt"] if r["VertexCnt"] is not None else 0,
                                             r["Mask"])
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

    regressed = []
    improved = []
    still_failing = []
    new_fail = []
    stable = 0

    def sig(row):
        """回归比较签名:BoneCnt/VertexCnt 总比;Mask 仅 cmp_mask 时纳入。"""
        bone, vert, mask = row
        return (bone, vert, mask) if cmp_mask else (bone, vert)

    for f in all_files:
        bp = f in b_ani
        cp = f in c_ani
        bf = f in b_fail
        cf = f in c_fail
        if bp:
            if not cp:
                regressed.append({"file": f, "from": "parsed", "to": "failed" if cf else "absent"})
            else:
                # 都解析了,比 BoneCnt/VertexCnt(及两侧都有的 Mask)
                if sig(b_ani[f]) != sig(c_ani[f]):
                    regressed.append({"file": f, "from": "parsed%s" % (sig(b_ani[f]),), "to": "parsed%s" % (sig(c_ani[f]),)})
                else:
                    stable += 1
        else:
            # baseline 非 parsed
            if cp:
                improved.append({"file": f, "from": "failed" if bf else "absent", "to": "parsed"})
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
        "regressed": len(regressed),
        "improved": len(improved),
        "still_failing": len(still_failing),
        "still_failing_knownbad": len(still_knownbad),
        "still_failing_unknown": len(still_unknown),
        "new_fail": len(new_fail),
    }
    result = {
        "baseline": args.baseline,
        "current": args.current,
        "counts": c_counts,
        "regressed": regressed,
        "improved": improved,
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
        print("stable=%d  improved=%d  regressed=%d  still_failing=%d(knownbad=%d unknown=%d)  new_fail=%d" %
              (c_counts["stable"], c_counts["improved"], c_counts["regressed"], c_counts["still_failing"],
               c_counts["still_failing_knownbad"], c_counts["still_failing_unknown"], c_counts["new_fail"]), file=hf)
        if regressed:
            print("\n[回归] 以下 ani 曾解析正常,本轮被破坏(必须回滚):", file=hf)
            for x in regressed[:20]:
                print("  %s  (%s -> %s)" % (x["file"], x["from"], x["to"]), file=hf)
            if len(regressed) > 20:
                print("  ... 另有 %d 条" % (len(regressed) - 20), file=hf)
        if improved:
            print("\n[改善] 以下 ani 由失败转为解析成功:", file=hf)
            for x in improved[:20]:
                print("  %s  (%s -> parsed)" % (x["file"], x["from"]), file=hf)
            if len(improved) > 20:
                print("  ... 另有 %d 条" % (len(improved) - 20), file=hf)
        if still_unknown:
            print("\n[仍失败-未归类] 需人工裁定(真坏文件 vs 复刻仍落后):", file=hf)
            for x in still_unknown[:20]:
                print("  %s" % x["file"], file=hf)

    has_regress = bool(regressed or new_fail)
    verdict = "PASS" if not has_regress else "FAIL"
    print("\n结论: %s" % verdict, file=hf)
    return 1 if has_regress else 0


if __name__ == "__main__":
    sys.exit(main())
