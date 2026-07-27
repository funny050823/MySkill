#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regen_scanlist.py — 为 Jx3SvnHookCheckTool.exe 生成扫描清单 ScanFileList.txt(代码同步技能通用,环节6)。

7 个代码同步技能(Pss/kmsc/Ani/tani/krl/SRScene/State)共享此一份(收敛自各技能副本)。
各技能差异仅在调用时传的 --root(扫描子目录)和 --ext(扩展名),脚本本身通用。

要点(与本仓库约定一致):
  - 清单文件必须是 GBK(cp936)、每行 1 个绝对路径,Windows 反斜杠。
  - 工具读取时 setlocale(LC_ALL,".936"),中文路径按 GBK 解。
  - 绝不能用 Edit/Write 工具生成(它们按 UTF-8 写会破坏中文);本脚本用 GBK 写。
  - ext 大小写不敏感(fn.lower().endswith),匹配磁盘大写扩展名(如 .SRScene)。

用法:
  python regen_scanlist.py --root <目录> --ext <扩展名> --out <清单文件> [--subset PATH] [--dry-run]
       (默认 --root 取 $JX3_HD_Client,未设且不传 --root → exit 2;--ext 无默认,必传或用默认 pss)

各技能用法示例:
  Pss:   --root "$JX3_HD_Client/data/source/other" --ext pss   --out .../ScanFileList_pss.txt
  kmsc:  --root "$JX3_HD_Client/data/movie"       --ext kmsc  --out .../ScanFileList_kmsc.txt
  Ani:   --root "$JX3_HD_Client"                  --ext ani   --out .../ScanFileList_ani.txt
  tani:  --root "$JX3_HD_Client"                  --ext tani  --out .../ScanFileList_tani.txt
  krl:   --root "$JX3_HD_Client/represent/rl"     --ext krl   --out .../ScanFileList_krl.txt
  SRScene:--root "$JX3_HD_Client/data/source/maps" --ext srscene --out .../ScanFileList_srscene.txt
  State: --root "$JX3_HD_Client/data/source/maps_source" --ext state --out .../ScanFileList_state.txt

退出码: 0 成功; 2 没收集到任何文件/未设 env 且未传 --root; 其它 1 异常。
"""
import argparse
import os
import sys

# 仓库根 = 本脚本所在 .claude/skills/_common/scripts 上溯 4 级
# (注:经软链时 SCRIPT_DIR 指向 MySkill 真实路径,此默认 REPO_ROOT 仅用于默认 --out;
#  实际调用总带显式 --out "$REPO/...",故此默认值不被使用,不影响。)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..", ".."))

# 默认扫描根: 取自环境变量 JX3_HD_Client(各技能 §1 前置已查;未设则须显式传 --root)。
# 各技能 SKILL.md §5.1 均显式传 --root "$JX3_HD_Client/<子目录>",故此默认值通常不被使用。
_CLIENT = os.environ.get("JX3_HD_Client")
_DEFAULT_ROOT = _CLIENT  # 默认整个 client;各技能传子目录覆盖


def collect_from_dir(root, ext):
    """递归收集 root 下所有 *.ext 的绝对路径(Windows 反斜杠)。ext 大小写不敏感(.lower() 比)。"""
    out = []
    ext_low = "." + ext.lower()
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(ext_low):
                out.append(os.path.abspath(os.path.join(dirpath, fn)))
    return out


def collect_from_list_file(path):
    """从清单文件读取路径(GBK 或 UTF-8 自动判),原样去重保序。"""
    out = []
    seen = set()
    raw = open(path, "rb").read()
    for enc in ("gbk", "utf-8-sig", "utf-8", "cp936"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = None
    if text is None:
        raise RuntimeError("无法识别清单文件编码(非 GBK/UTF-8):%s" % path)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = os.path.abspath(line)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description="生成 GBK 扫描清单 ScanFileList.txt(代码同步技能通用)")
    ap.add_argument("--root", default=_DEFAULT_ROOT,
                    help="收集 *.ext 的根目录(默认 $JX3_HD_Client;各技能传 $JX3_HD_Client/<子目录>;env 未设须显式传)")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "x64", "Release", "logs", "ScanFileList.txt"),
                    help="输出清单文件路径")
    ap.add_argument("--ext", default="pss", help="扩展名(必传或默认 pss;大小写不敏感,匹配磁盘大写如 .SRScene)")
    ap.add_argument("--subset", default=None,
                    help="子集:目录(只在其下收集)或清单文件(读取其内路径)。设此项则忽略 --root")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    args = ap.parse_args()

    if args.subset:
        if os.path.isdir(args.subset):
            paths = collect_from_dir(args.subset, args.ext)
            src = "subset-dir:%s" % args.subset
        elif os.path.isfile(args.subset):
            paths = collect_from_list_file(args.subset)
            src = "subset-list:%s" % args.subset
        else:
            print("错误:--subset 既不是目录也不是文件:%s" % args.subset, file=sys.stderr)
            return 1
    else:
        if not args.root:
            print("错误:未设环境变量 JX3_HD_Client 且未传 --root(§1 前置要求 JX3_HD_Client 必须存在),技能终止", file=sys.stderr)
            return 2
        if not os.path.isdir(args.root):
            print("错误:--root 不是目录:%s" % args.root, file=sys.stderr)
            return 1
        paths = collect_from_dir(args.root, args.ext)
        src = "root:%s" % args.root

    paths = sorted(set(paths))
    print("来源: %s" % src)
    print("收集到 %d 个 .%s 文件" % (len(paths), args.ext))

    if not paths:
        print("RESULT status=empty collected=0", file=sys.stderr)
        print("警告:没有收集到任何文件,不写清单。", file=sys.stderr)
        return 2

    if args.dry_run:
        print("RESULT status=dryrun collected=%d" % len(paths))
        print("[dry-run] 前 5 条示例:")
        for p in paths[:5]:
            print("  " + p)
        return 0

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    # GBK + CRLF,Windows 反斜杠路径。abspath 已给反斜杠。
    n = 0
    with open(args.out, "w", encoding="gbk", newline="") as f:
        for p in paths:
            f.write(p + "\r\n")
            n += 1
    print("已写出(GBK/CRLF):%s  共 %d 行" % (args.out, n))
    # ASCII 汇总行:任何控制台编码下 Claude 都能稳定解析计数与输出路径
    print("RESULT status=ok collected=%d written=%s" % (n, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
