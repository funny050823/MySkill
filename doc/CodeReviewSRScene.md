# SRScene 解析复刻代码技能实现详细过程文档

本技能和`Pss代码同步`技能大体相同，我这里列出异同点。你帮我写个完整的`SRScene代码同步`技能。

注意：

本文绝对路径都需要替换成环境变量哦，避免技能换台机器，就执行失败的情况。提示环境变量有：
JX3ENGINE_Sword3
JX3ENGINE_BASE
JX3ENGINE_DevEnv
JX3_HD_Client
MSBuildTool

本技能同`Pss代码同步`技能一样，也只在windows下执行。

## 1. 锁定路径（别取错）
- 前置环境检查 同`Pss代码同步`
- 项目路径(仓库根) 同`Pss代码同步`
- 复刻侧 不同于`Pss代码同步`

  - 复刻函数
    - 项目：d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj
    - 涉及文件：D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\src\SRScene\SRScene.cpp
    - 复刻函数：SRScene::ReadFile

  - 引擎原函数：
    - 项目：d:\JX3\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\Module\KG3DSceneResponse\KG3DEntitySystem_2019.vcxproj
    - 引擎文件：D:\JX3\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\Module\KG3DSceneResponse\KSRScene.cpp
    - 原函数：KSRScene::LoadFromFile

## 2. 差异比对法（每轮第一步）不同于`Pss代码同步`

- 需要你去总结

## 3. 三类信息抽取（同步时的不变量，必须守）于`Pss代码同步`一同点

### 3.1 明文引用其他文件路径标签（必须捞，重点项）同`Pss代码同步`
### 3.2 音频标签（必须捞，重点项） SRScene没有音频标签
### 3.3 特效数据（写 m_pssInfo / 成员计数器）（必须捞，重点项）SRScene没有音频标签


## 4. 构建/部署 同`Pss代码同步`

## 5. 执行方法或流程 

### 第一步 编写脚本 同于`Pss代码同步`

### 第二步 深度检索 pss 出清单 不同于`Pss代码同步`
  - 深度扫描 $JX3_HD_Client/data\source\maps\ 路径下 .SRScene 文件，生成清单

### 第三步 执行 Jx3LocalResScanTool.cmd 与`Pss代码同步`存在差异
  - 不需要执行 KSearchResource.exe 搜索音频标签信息
  - 其他的都一样

### 第四步 检查报告完整性 与`Pss代码同步`差异只有1点
  - SQLite3数据库文件:ScanResult.db 不关注Pss表，其他检查点都完全一样

## 6. 出代码修改前后，对比测试报告 与`Pss代码同步`差异只有1点
  - SQLite3数据库文件:ScanResult.db 不关注Pss表，其他检查点都完全一样
