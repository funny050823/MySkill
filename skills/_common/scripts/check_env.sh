#!/usr/bin/env bash
# check_env.sh — 代码同步技能通用前置环境检查(环节1,通用)。
# 6 项:4 环境变量(JX3ENGINE_Sword3/JX3ENGINE_BASE/JX3ENGINE_DevEnv/JX3_HD_Client)+ MSBuildTool + svn wc.db。
# 任一缺失/无效 → 打印 "缺失/无效,技能终止" + exit 1;全 OK → exit 0。
#
# 用法(各技能 SKILL.md §1):
#   bash "$REPO/.claude/skills/_common/scripts/check_env.sh" || exit 1
#   # 经软链:_common 也是 junction → d:/StudyAndroid/MySkill/skills/_common
#
# 全 OK 后,wc.db 路径 stdout 打印一行(供调用方复用,避免再判 ../.svn vs .svn):
#   WCDB=<实际 wc.db 绝对路径>
set -u

ok=1
for v in JX3ENGINE_Sword3 JX3ENGINE_BASE JX3ENGINE_DevEnv JX3_HD_Client; do
  val="${!v:-}"
  if [ -n "$val" ] && [ -d "$val" ]; then
    echo "$v OK=$val"
  else
    echo "$v 缺失/无效,技能终止"
    ok=0
  fi
done

if [ -f "${MSBuildTool:-}" ]; then
  echo "MSBuildTool OK=$MSBuildTool"
else
  echo "MSBuildTool 缺失/无效,技能终止"
  ok=0
fi

# svn wc.db:client 上级是副本根→../.svn,自身是副本根→.svn,两者必须存在一个
WCDB="${JX3_HD_Client:-}/../.svn/wc.db"
if [ ! -f "$WCDB" ]; then WCDB="${JX3_HD_Client:-}/.svn/wc.db"; fi
if [ -f "$WCDB" ]; then
  echo "wc.db OK=$WCDB"
  echo "WCDB=$WCDB"   # 供调用方复用
else
  echo "wc.db 异常:\$JX3_HD_Client/../.svn/wc.db 和 \$JX3_HD_Client/.svn/wc.db 都不存在,技能终止"
  ok=0
fi

if [ $ok -ne 1 ]; then
  exit 1
fi
exit 0
