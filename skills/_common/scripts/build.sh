#!/usr/bin/env bash
# build.sh — 代码同步技能通用编译(环节5,通用)。
# 先编 RUST 依赖(KESMBase/ClipLib,FileParse.sln 不含这两个工程不会自动先编),
# 再 rebuild FileParse.sln 出 Jx3SvnHookCheckTool.exe。
#
# 依赖环境变量:MSBuildTool、JX3ENGINE_Sword3(由 check_env.sh 保证存在,先跑 check_env)。
# 依赖当前工作目录:仓库根 KResourceReader(用相对 FileParse.sln)。
#
# 用法(各技能 SKILL.md §4):
#   bash "$REPO/.claude/skills/_common/scripts/build.sh" || 退出
# 可选环境变量:
#   BUILD_SKIP_RUST=1  跳过 RUST 前置(lib 已最新时省时间,默认编)
set -u

if [ -z "${MSBuildTool:-}" ] || [ ! -f "$MSBuildTool" ]; then
  echo "错误:MSBuildTool 未设/无效,先跑 check_env.sh" >&2
  exit 1
fi
ENG="${JX3ENGINE_Sword3:-}"
if [ -z "$ENG" ] || [ ! -d "$ENG" ]; then
  echo "错误:JX3ENGINE_Sword3 未设/无效,先跑 check_env.sh" >&2
  exit 1
fi

# bash 下 MSBuild 的 / 参数写成 // (防 bash 当成路径)
SKIP_RUST="${BUILD_SKIP_RUST:-0}"

if [ "$SKIP_RUST" != "1" ]; then
  echo "=== 编译 RUST 依赖(KESMBase/ClipLib)==="
  "$MSBuildTool" "$ENG/Source/Common/RUST/KESMBase/KESMBase_2019.vcxproj" //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
  rc=$?
  if [ $rc -ne 0 ]; then echo "错误:KESMBase 编译失败(rc=$rc)" >&2; exit $rc; fi
  "$MSBuildTool" "$ENG/Source/Common/RUST/ClipLib/ClipLib_2019.vcxproj"  //p:Configuration=Release //p:Platform=x64 //nologo //v:minimal
  rc=$?
  if [ $rc -ne 0 ]; then echo "错误:ClipLib 编译失败(rc=$rc)" >&2; exit $rc; fi
fi

echo "=== rebuild FileParse.sln ==="
"$MSBuildTool" FileParse.sln //property:Configuration=Release //t:rebuild //nologo //v:minimal
rc=$?
if [ $rc -ne 0 ]; then
  echo "错误:FileParse.sln 编译失败(rc=$rc)。LNK1104 打不开 dll/exe → 多半遗留 Jx3* 进程锁着(tasklist | grep Jx3 + taskkill //PID //F)或 RUST lib 没编" >&2
  exit $rc
fi
echo "=== 编译成功 ==="
exit 0
