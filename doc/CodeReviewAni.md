# Ani 解析复刻代码技能实现详细过程文档

本技能和`Pss代码同步`技能大体相同，我这里只列出差异的地方。你帮我写个完整的`Ani代码同步`技能。

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
    - 涉及文件：D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\src\Ani\Ani.cpp
    - 复刻函数：Ani::ReadFile

  - 引擎原函数：
    - 项目：d:\JX3\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_Model\KG3D_Model_2019.vcxproj
    - 引擎文件：d:\JX3\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_Model\KG3D_Animation.cpp
    - 原函数：KG3D_Animation::LoadFromFile

## 2. 差异比对法（每轮第一步）不同于`Pss代码同步`

- 需要你去总结

## 3. 三类信息抽取（同步时的不变量，必须守）不同于`Pss代码同步`

- 需要提取的信息有(Ani类成员)
  - m_dwType:动画类型
  - m_dwNumBones:如果是骨骼动画，m_dwNumBones>0，代表骨骼数，否则为0
  - m_dwNumAnimatedVertices:如果是顶点动画，m_dwNumAnimatedVertices>0，代表顶点数，否则为0
  - m_bKeyFrame:是否为抽帧ani

## 4. 构建 同`Pss代码同步`

## 5. 测试（全量）

- 5.1 生成扫描清单(GBK!) 不同于`Pss代码同步`
  - 深度扫描 $JX3_HD_Client 路径下 .ani 文件，生成清单

- 5.2 跑扫描器(关键:ReadFileListFromSvnDB=0) 同`Pss代码同步`

- 5.3 读报告 存在不同`Pss代码同步`
  - 关注SQLite3数据 ScanResult.db 中的 Result 和 Ani 表
  - 其他的都相同

- 5.4 跑音频标签扫描(改码前后各一次,路径不同!) 没有这项

## 6、7、8、9 

- 对比测试报告（落盘 UpdateCodeAni.md）
- 音频标签相关的都过滤掉
- 修改代码前后，检查重点是SQLite3数据库 ScanResult.db 中的 Result 和 Ani 表差异
