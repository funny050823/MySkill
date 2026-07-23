#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_scanresult.py — 对比两次全量扫描的 ScanResult.db,给出"回归保护"判据。

用途: Pss代码同步技能里,改复刻代码前跑一次全量得 baseline.db,改+编译后再跑一次
      得 current.db,用本脚本对比,判断本轮同步是否引入回归、目标文件是否改善。

判据(与 SKILL.md §6 一致):
  regressed(回归)  : baseline 在 Pss 表(曾解析 OK) -> current 不在 Pss,或在但
                     特效字段/PssLoop 变了。非空 => 本轮不通过,回滚重来。
  improved(改善)  : baseline 解析失败 -> current 进了 Pss 表。本轮目标文件应在此。
  still_failing   : 两次都失败。与 --knownbad 交集 = 预期坏文件(如截断 .pss),不计回归;
                     其余 = 待人工裁定的新/旧失败。
  new_fail        : baseline 没扫到、current 却失败的(同清单下一般不出现,出现即异常)。

数据来源(同一份 ScanResult.db,路径格式一致,均为相对反斜杠路径):
  Pss        : 特效数据(9 字段 + SkipIgnore)
  PssLoop    : 循环计数(nLauncherCnt 等)
  Result     : ErrLevel=7 即解析失败
  FileListInput : 扫描清单(用于 sanity 计数)

用法:
  python diff_scanresult.py <baseline.db> <current.db> [--knownbad FILE] [--json] [--quiet]

退出码: 0 无回归; 1 有回归(regressed 或 new_fail 非空); 2 输入异常。
"""
import argparse
import json
import os
import sqlite3
import sys

PSS_FIELDS = ["LaucherNumMax", "MobileLauncherMax", "ParticleNumMax", "MaterialNum",
              "MeshQuoteNum", "MeshQuoteVertexNum", "BBoxX", "BBoxY", "BBoxZ",
              "TrackCnt", "SkipIgnore"]
LOOP_FIELDS = ["nLauncherCnt", "nUnlimitLauncherLoopCnt", "nParticleCnt", "nUnlimitLoopParticleCnt"]


def norm(s):
    if s is None:
        return ""
    return s.strip().lower().replace("/", "\\")


def connect(db):
    if not os.path.isfile(db):
        raise RuntimeError("db 不存在: %s" % db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def read_table(db, label, sql, key_col):
    """通用读取: 返回 {norm(key): {col: val}}。表缺失/空返回 {}。"""
    out = {}
    try:
        con = connect(db)
        cur = con.execute(sql)
        for r in cur.fetchall():
            out[norm(r[key_col])] = {k: r[k] for k in r.keys() if k != key_col}
        con.close()
    except sqlite3.Error as e:
        print("warn: 读取 %s 失败(%s): %s" % (label, db, e), file=sys.stderr)
    except RuntimeError as e:
        print("错误: %s" % e, file=sys.stderr)
        raise
    return out


def read_set(db, label, sql, key_col):
    out = set()
    try:
        con = connect(db)
        cur = con.execute(sql)
        for r in cur.fetchall():
            out.add(norm(r[key_col]))
        con.close()
    except sqlite3.Error as e:
        # sanity 表(如 FileListInput)在某些扫描模式下不建,缺了属正常,静默
        if "no such table" not in str(e):
            print("warn: 读取 %s 失败(%s): %s" % (label, db, e), file=sys.stderr)
    return out


def read_pss(db):
    cols = ",".join(PSS_FIELDS)
    return read_table(db, "Pss",
                      "SELECT FilePath,%s FROM Pss" % cols, "FilePath")


def read_pssloop(db):
    cols = ",".join(LOOP_FIELDS)
    return read_table(db, "PssLoop",
                      "SELECT File,%s FROM PssLoop" % cols, "File")


def read_fail(db):
    # ErrLevel=7 = 解析失败; 取 pss 文件(File 以 .pss 结尾 或 ExtName=pss)
    return read_set(db, "Result(pss fail)",
                    "SELECT DISTINCT File AS F FROM Result "
                    "WHERE ErrLevel=7 AND (lower(File) LIKE '%.pss' OR lower(IFNULL(ExtName,''))='pss')",
                    "F")


def read_scanned(db):
    return read_set(db, "FileListInput",
                    "SELECT File AS F FROM FileListInput", "F")


def read_audiolabel(db):
    """读 AudioLabel.db 的 File(File,EventName,AudioFile) 表,只取 .pss。
    返回 set of (norm(File), EventName, AudioFile)。
    AudioLabel.db 由 KSearchResource.exe SearchAudioLabel 全库扫音频标签产出,
    pss 的 AddWwiseEvent/AddFmod 都落这里(扫 data\source\other 下 .pss)。
    表缺失则返回空 set(--audiolabel 未提供时不调用)。
    """
    out = set()
    try:
        con = connect(db)
        cur = con.execute(
            "SELECT File, EventName, AudioFile FROM File "
            "WHERE lower(File) LIKE '%.pss'")
        for r in cur.fetchall():
            out.add((norm(r["File"]),
                     r["EventName"] if r["EventName"] is not None else "",
                     r["AudioFile"] if r["AudioFile"] is not None else ""))
        con.close()
    except sqlite3.Error as e:
        if "no such table" in str(e):
            print("warn: AudioLabel.db 无 File 表(%s): 可能非 SearchAudioLabel 产出" % db, file=sys.stderr)
        else:
            print("warn: 读取 AudioLabel 失败(%s): %s" % (db, e), file=sys.stderr)
    except RuntimeError as e:
        print("错误: %s" % e, file=sys.stderr)
        raise
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


def effect_sig(pss_row, loop_row):
    """合并 Pss 字段 + PssLoop 字段为可比较签名。"""
    sig = []
    for k in PSS_FIELDS:
        sig.append((k, pss_row.get(k) if pss_row else None))
    for k in LOOP_FIELDS:
        sig.append((k, loop_row.get(k) if loop_row else None))
    return tuple(sig)


def main():
    ap = argparse.ArgumentParser(description="对比两份 ScanResult.db 的回归判据")
    ap.add_argument("baseline", help="改码前 baseline ScanResult.db")
    ap.add_argument("current", help="改码后 current ScanResult.db")
    ap.add_argument("--knownbad", default=None, help="已知坏文件清单(每行一个 pss 路径)")
    ap.add_argument("--audiolabel", nargs=2, metavar=("BASE_AUDIO", "CUR_AUDIO"), default=None,
                    help="可选: 两份 AudioLabel.db(baseline/current,由 KSearchResource.exe "
                         "SearchAudioLabel 产出),对比 .pss 音频标签(File,EventName,AudioFile)前后变化。"
                         "audio_removed=漏抽音频=回归")
    ap.add_argument("--json", action="store_true", help="额外输出 machine-readable JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总计数")
    args = ap.parse_args()

    for db in (args.baseline, args.current):
        if not os.path.isfile(db):
            print("错误: db 不存在: %s" % db, file=sys.stderr)
            return 2

    kb = load_knownbad(args.knownbad)

    b_pss = read_pss(args.baseline)
    b_loop = read_pssloop(args.baseline)
    b_fail = read_fail(args.baseline)
    b_scan = read_scanned(args.baseline)

    c_pss = read_pss(args.current)
    c_loop = read_pssloop(args.current)
    c_fail = read_fail(args.current)
    c_scan = read_scanned(args.current)

    # 音频标签对比(可选,经 --audiolabel 提供 AudioLabel.db)
    audio_removed = []   # 回归: baseline 有、current 无(漏抽音频)
    audio_added = []      # 改善: current 有、baseline 无(多抽)
    b_audio = c_audio = set()
    if args.audiolabel:
        for db in args.audiolabel:
            if not os.path.isfile(db):
                print("错误: AudioLabel.db 不存在: %s" % db, file=sys.stderr)
                return 2
        b_audio = read_audiolabel(args.audiolabel[0])
        c_audio = read_audiolabel(args.audiolabel[1])
        audio_removed = sorted(b_audio - c_audio)
        audio_added = sorted(c_audio - b_audio)

    # 解析状态判定
    def status(f, pss, fail, scan):
        if f in pss:
            return "parsed"
        if f in fail:
            return "failed"
        if f in scan:
            return "missed"  # 扫了但既没进 Pss 也没报错 = 静默跳过
        return "absent"

    all_files = set(b_pss) | set(c_pss) | b_fail | c_fail | b_scan | c_scan

    regressed = []
    improved = []
    still_failing = []
    new_fail = []
    stable = 0

    for f in all_files:
        bs = status(f, b_pss, b_fail, b_scan)
        cs = status(f, c_pss, c_fail, c_scan)
        if bs == "parsed":
            if cs != "parsed":
                regressed.append({"file": f, "from": "parsed", "to": cs})
            else:
                # 都解析了,比特效签名
                if effect_sig(b_pss.get(f), b_loop.get(f)) != effect_sig(c_pss.get(f), c_loop.get(f)):
                    regressed.append({"file": f, "from": "parsed(fields-changed)", "to": "parsed(fields-changed)"})
                else:
                    stable += 1
        else:
            # baseline 非 parsed
            if cs == "parsed":
                improved.append({"file": f, "from": bs, "to": "parsed"})
            elif cs == "failed":
                if bs == "failed":
                    still_failing.append({"file": f})
                elif bs == "absent":
                    new_fail.append({"file": f, "from": "absent", "to": "failed"})
                else:  # missed -> failed
                    new_fail.append({"file": f, "from": bs, "to": "failed"})
            # cs == missed / absent 且 bs != parsed: 非回归(本来就坏/没扫到)

    still_knownbad = [x for x in still_failing if x["file"] in kb]
    still_unknown = [x for x in still_failing if x["file"] not in kb]

    result = {
        "baseline": args.baseline,
        "current": args.current,
        "counts": {
            "baseline_parsed": len(b_pss),
            "current_parsed": len(c_pss),
            "baseline_failed": len(b_fail),
            "current_failed": len(c_fail),
            "baseline_scanned": len(b_scan),
            "current_scanned": len(c_scan),
            "stable": stable,
            "regressed": len(regressed),
            "improved": len(improved),
            "still_failing": len(still_failing),
            "still_failing_knownbad": len(still_knownbad),
            "still_failing_unknown": len(still_unknown),
            "new_fail": len(new_fail),
            "audio_baseline": len(b_audio),
            "audio_current": len(c_audio),
            "audio_removed": len(audio_removed),
            "audio_added": len(audio_added),
        },
        "regressed": regressed,
        "improved": improved,
        "still_failing_knownbad": still_knownbad,
        "still_failing_unknown": still_unknown,
        "new_fail": new_fail,
        "audio_removed": audio_removed,
        "audio_added": audio_added,
    }

    c = result["counts"]
    # --json 时 stdout 只留纯 JSON,人类摘要/结论走 stderr,便于管道解析
    hf = sys.stderr if args.json else sys.stdout

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.quiet:
        print("baseline: parsed=%d failed=%d scanned=%d" %
              (c["baseline_parsed"], c["baseline_failed"], c["baseline_scanned"]), file=hf)
        print("current : parsed=%d failed=%d scanned=%d" %
              (c["current_parsed"], c["current_failed"], c["current_scanned"]), file=hf)
        print("stable=%d  improved=%d  regressed=%d  still_failing=%d(knownbad=%d unknown=%d)  new_fail=%d" %
              (c["stable"], c["improved"], c["regressed"], c["still_failing"],
               c["still_failing_knownbad"], c["still_failing_unknown"], c["new_fail"]), file=hf)
        if args.audiolabel:
            print("音频标签: baseline=%d current=%d  audio_removed(回归)=%d  audio_added(改善)=%d" %
                  (c["audio_baseline"], c["audio_current"], c["audio_removed"], c["audio_added"]), file=hf)
        if regressed:
            print("\n[回归] 以下文件曾解析正常,本轮被破坏(必须回滚):", file=hf)
            for x in regressed[:20]:
                print("  %s  (%s -> %s)" % (x["file"], x["from"], x["to"]), file=hf)
            if len(regressed) > 20:
                print("  ... 另有 %d 条" % (len(regressed) - 20), file=hf)
        if audio_removed:
            print("\n[回归-音频] 以下 .pss 音频标签 baseline 有、current 无(漏抽,必须回滚):", file=hf)
            for x in audio_removed[:20]:
                print("  %s | %s | %s" % x, file=hf)
            if len(audio_removed) > 20:
                print("  ... 另有 %d 条" % (len(audio_removed) - 20), file=hf)
        if improved:
            print("\n[改善] 以下文件由失败转为解析成功:", file=hf)
            for x in improved[:20]:
                print("  %s  (%s -> parsed)" % (x["file"], x["from"]), file=hf)
            if len(improved) > 20:
                print("  ... 另有 %d 条" % (len(improved) - 20), file=hf)
        if still_unknown:
            print("\n[仍失败-未归类] 需人工裁定(真坏文件 vs 复刻仍落后):", file=hf)
            for x in still_unknown[:20]:
                print("  %s" % x["file"], file=hf)
            if len(still_unknown) > 20:
                print("  ... 另有 %d 条" % (len(still_unknown) - 20), file=hf)

    has_regress = bool(regressed or new_fail or audio_removed)
    verdict = "PASS" if not has_regress else "FAIL"
    print("\n结论: %s" % verdict, file=hf)
    return 1 if has_regress else 0


if __name__ == "__main__":
    sys.exit(main())
