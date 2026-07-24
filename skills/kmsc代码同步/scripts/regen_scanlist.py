#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regen_scanlist.py — 为 Jx3SvnHookCheckTool.exe 生成扫描清单 ScanFileList.txt。

要点(与本仓库约定一致):
  - 清单文件必须是 GBK(cp936)、每行 1 个绝对路径,Windows 反斜杠。
  - 工具读取时 setlocale(LC_ALL,".936"),中文路径按 GBK 解。
  - 绝不能用 Edit/Write 工具生成(它们按 UTF-8 写会破坏中文);本脚本用 GBK 写。

用法:
  python regen_scanlist.py [--root DIR] [--out FILE] [--ext pss] [--subset PATH] [--dry-run]

默认:
  --root  D:/JX3/trunk/sword3-products/trunk/client/data/source/other
  --out   <repo>/x64/Release/logs/ScanFileList.txt
  --ext   pss
  --subset  可选:传一个目录(只在该目录下收集)或一个清单文件(每行一个路径,原样去重)。
          传了 --subset 时,--root 被忽略。

退出码: 0 成功; 2 没收集到任何文件; 其它 1 异常。
"""
import argparse
import os
import sys

# 仓库根 = 本脚本所在 .claude/skills/Pss代码同步/scripts 上溯 4 级
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..", ".."))


def collect_from_dir(root, ext):
    """递归收集 root 下所有 *.ext 的绝对路径(Windows 反斜杠)。"""
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
    ap = argparse.ArgumentParser(description="生成 GBK 扫描清单 ScanFileList_kmsc.txt")
    ap.add_argument("--root", default=r"D:\JX3\trunk\sword3-products\trunk\client\data\movie",
                    help="收集 *.kmsc 的根目录(默认 data\movie\)")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "x64", "Release", "logs", "ScanFileList_kmsc.txt"),
                    help="输出清单文件路径")
    ap.add_argument("--ext", default="kmsc", help="扩展名(默认 kmsc)")
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
