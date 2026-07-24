# Pss 解析复刻代码技能实现详细过程文档

> 复刻函数 `Pss::ReadFile` 对标引擎原函数 `KG3D_ParticleFileData::LoadFromFile`，解析 `.pss` 资源。

> 本文档梳理：复刻与原函数的**读取差异**、复刻需从 pss 抽取的**三类信息**。

> 用途：检查复刻函数代码 与 引擎原函数代码 读取Pss文件是否保持一致;复刻函数会落后于引擎原函数；引擎新增或修改类型/结构体时,复刻函数若没同步，复刻函数在解析pss类型资源的时候,遇到新类型pss就会解析失败或漏解析重要数据.本技能,自动对比复刻函数和原函数差异,修改复刻函数代码,自动编译代码,执行测试,并进行测试结果前后对比,直至复刻函数解析逻辑完全符合要求为止.

---

## 1. 复刻关系与原函数路径（锁定，别取错）

- 复刻函数
  - 项目：d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\Jx3ResFileReaderAPI\Jx3ResFileReaderAPI.vcxproj
  - 涉及文件：`D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\src\Pss\Pss.cpp` + `HeaderPss.h` + `Pss.h`
    - 如果`D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\src\Pss\Pss.cpp`不存在,请检查`%cd%\..\src\Pss\Pss.cpp`,`%cd%`是指当前.md文件路径.
  - 复刻函数：Pss::ReadFile
- 引擎原函数
  - 项目：d:\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleSystem_2019.vcxproj
  - 引擎文件：`D:\JX3\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleFileData.cpp`
    - 如果 `D:\JX3\trunk\Sword3`路径不存在，请检查是否存在环境变量：`%JX3ENGINE_Sword3%`，如果存在，引擎文件就是：`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\Component\KG3D_ParticleSystem\KG3D_ParticleFileData.cpp`
    - 复刻还依赖引擎的头文件作口径来源：
      - `IKE3D_ParticleType.h`（`PARSYS_LAUNCHER_*` / `PARSYS_CT_*` 枚举），真实路径：`D:\JX3\trunk\Sword3\Source\KG3DEngineDX11\KG3DEngineE\Internal\InternalPublish\Include\ParticleSystem\IKE3D_ParticleType.h`
        - 注意：该文件在 `InternalPublish\Include\ParticleSystem\` 下，**不在** `...\Component\KG3D_ParticleSystem\` 下，别取错。
        - 如果 `D:\JX3\trunk\Sword3` 路径不存在，请检查是否存在环境变量：`%JX3ENGINE_Sword3%`，如果存在，该文件就是：`%JX3ENGINE_Sword3%\Source\KG3DEngineDX11\KG3DEngineE\Internal\InternalPublish\Include\ParticleSystem\IKE3D_ParticleType.h`
      - `KG3D_ParticleFileDeclare.h`（`KG3D_PARSYS_*_STATIC_DATA` 结构体），在 `...\Component\KG3D_ParticleSystem\` 下。
      - `KG3D_ParticleLauncher.cpp` + `KG3D_ParticleLauncher.h`（各 `KG3D_ParticleXxxLauncher::ReadData` 逐类型读取逻辑，在 `...\Component\KG3D_ParticleSystem\` 下）。逐类型同步新发射器类型时按字节级对标的真正落点。
  - 引擎原函数：KG3D_ParticleFileData::LoadFromFile

---

## 2. 函数级映射

| 复刻 (`Pss.cpp`) | 原函数 (`KG3D_ParticleFileData.cpp`) | 关系 |
|---|---|---|
| `Pss::ReadFile`  | `KG3D_ParticleFileData::LoadFromFile`  | 顶层元素表遍历 |
| `Pss::_PARSYS_ReadParticleLauncherBlock`  | `_PARSYS_ReadParticleLauncherBlock`  |  |
| `Pss::KG3D_ParticlePreCompute_ReadData` | `KG3D_ParticlePreCompute::ReadData` | 等价 |
| `Pss::KG3D_ParticleModule_ReadData`  | 各 `KG3D_ParticleModule::ReadData` 派生类 |  |

---

## 3. 复刻函数需从 pss 抽取的三类信息

复刻不只"解析成功"，还要抽信息供资源检查/入库。特效数据写进 `m_pssInfo`（结构定义在 `include/IJx3ResFileReader.h:387` `PssInfo`）。

### 3.1 明文引用其他文件路径标签（必须捞，重点项）

**捞取口径（重要）：解析pss过程中,只要发现`MAX_PATH`或`FILENAME_MAX`宏,就参与 `Reference(..., sizeof(char)*MAX_PATH)` 这类读取，就都可能是外部资源路径，一律捞出来，由人工核实是否真是资源路径。不要靠字段名过滤，以宏为信号，宁多勿漏。**

登记接口：`OnReadResourceFileByGBK(路径, ...)`。当前已知登记点（按 `Pss.cpp` 行号，会随代码变动）：

| 来源块 | 字段 | 行号 | 备注 |
|---|---|---|---|
| 材质块 `KG3D_MaterialBase_LoadFromBuffer` | 材质定义名 `szDefineName` | `:293` | |
| 材质块 | 贴图文件名 `pszFile` | `:353` | 仅 texture 循环登记 |
| 材质块 | float/vec/color 等参数名 | `:361`等 | 当前注释掉只跳过，但仍是 `MAX_PATH` 读取，按口径属**候选**，需确认是否要登记 |
| Track 块 `_PARSYS_ReadParticleTrackBlock` | `byTrackFileName` | `:1386` | |
| 声音引用发射器 `KG3D_ParticleSoundQuoteLauncher_ReadData` | `bySoundName` | `:1216` | 仅 `.ogg/.wav/.mp3` 结尾才登记明文 |
| Mesh 发射器 `KG3D_ParticleMeshLauncher_ReadData` | `byMeshName` | `:1233` | 仅 `PARSYS_PARTICLE_SHAPE_CUSTOM` |
| GPU Mesh 发射器 `KG3D_CollectMeshLauncher_ReadData` | `byStringName` | `:1251` | |
| 力场引用发射器 `KG3D_ParticleForceFieldQuoteLauncher_ReadData` | `szFieldFilePath` | `:1267` | .fga 力场路径，非空才登记 |
| 模型引用发射器 `KG3D_ParticleMeshQuoteLauncher_ReadData` | `byAnimationName` | `:1317` | |
| 模型引用发射器 | `byMeshName` | `:1318` | |
| 模型引用发射器 | `byMtlInsPackName` | `:1319` | |

### 3.2 音频标签（必须捞，重点项）

**凡是原函数/复刻里涉及音效标签的，一律捞出来，不得漏。**

音效标签分两类: WwiseEvent事件 和 Fmod 标签. 登记接口：
- WwiseEvent事件:`KGShare::SoundLabel::Instance().AddWwiseEvent`
- Fmod 标签:`AddFmod`。

| 来源块 | 调用 | 行号 | 对应类型 |
|---|---|---|---|
| WWISE 发射器 `KG3D_ParticleWwiseLauncher_ReadData` | `AddWwiseEvent(GetSrcFile(), byEvent)` | `:1189` | `PARSYS_LAUNCHER_WWISE` |
| 声音引用发射器 `KG3D_ParticleSoundQuoteLauncher_ReadData` | `AddFmod(GetSrcFile(), bySoundName)` | `:1210` | `PARSYS_LAUNCHER_SOUNDQUOTE` |

> 新增带音频的发射器类型/模块，必须补登记，否则漏抽音效标签。

### 3.3 特效数据（写 `m_pssInfo` / 成员计数器）（必须捞，重点项）

`PssInfo` 字段（`IJx3ResFileReader.h:387-429`）：

| 字段 | 含义 | 来源 | 行号 |
|---|---|---|---|
| `nBBoxX/Y/Z` | 包围盒尺寸 = `AABBoxMax - AABBoxMin`（取整） | GeneralInfo 块 | `:130-132` |
| `dwParticleNumMax` | 最大粒子数 | GeneralInfo 块 `dwMaxParticle` | `:134` |
| `nMaterialNum` | 材质数 | 材质块每块 +1 | `:204` |
| `vnNumPlay` | 发射器播放次数，0=无限循环 | 每 launcher `nNumPlay` | `:1019` |
| `nMobileLauncher` | 移动端发射器数 | `byMobileLauncher==1\|\|2` | `:1025` |
| `nLaucherNumMax` | 发射器总数 | 每 launcher 块 +1 | `:1163` |
| `vdwLoopCount` | `PARSYS_CT_PARTICLE_LIFETIME` 模块第2参(j==1)循环次数，0=无限循环 | 模块循环 | `:586` |
| `nMeshQuoteNum` | 模型引用发射器数 | 模型引用发射器块 | `:1324` |
| `nMeshQuoteVertexNum` | 累计各引用 mesh 顶点数，取不到置 -1 | `GetMeshNumVertices` 现读 .mesh 文件头 | `:1335` |
| `nTrackCnt` | Track 块数 | Track 块每块 +1 | `:1387` |

非 `PssInfo` 的成员计数器：
- `m_nLauncherSignificance` / `m_nLauncherSignificanceLess2`（手机核心发射器统计，`:1027/1030`）
- `m_nMobileLodCnt[4]`（`FORMBOBILELODCOUNT` 编译开关，`:1039`）
- `m_ppMeshFile[]`（引用 mesh 文件名数组，`:1323`）
- `MESH_MAX_CNT = 512`（`:140`），`nMeshQuoteNum` 超出报错。

---

## 4. 构建/部署 <a id="BuildSln"></a>
- 编译整个解决方案 `FileParse.sln`，产出在 `Jx3ResFileReaderAPI/x64/Release/`。

## 5. 执行方法或流程

### 第一步 编写脚本
参考 `d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\logs\Jx3LocalResScanTool.cmd`：
```bat
rem 执行 Jx3SvnHookCheckTool.exe
set ExeFile=D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\Jx3SvnHookCheckTool.exe
set ClientPath=D:\JX3\trunk\sword3-products\trunk\client
set DBFile=D:\JX3\trunk\sword3-products\trunk\.svn\wc.db
set ScanList=D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\logs\ScanFileList.txt
rem 全量扫描必须 ReadFileListFromSvnDB=0：=1 会去 svn wc.db 读改动文件，不是全量；
rem =0 才走 ScanByFileList 精确扫 ScanList 清单里的所有文件。
set ReadFileListFromSvnDB=0
call "%ExeFile%" "%ClientPath%" "%DBFile%" "%ScanList%"

rem 执行 KSearchResource.exe
set ExeFile=D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\KSearchResource.exe
set AudioLabelDB=D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\logs\AudioLabel.db
call "%ExeFile%" SearchAudioLabel "%ClientPath%" "%AudioLabelDB%"
```

**注意** AudioLabelDB 路径设置问题：修改代码前，和修改代码后不能使用相同文件路径，否则后跑的测试会把先跑的测试覆盖掉，后面就没法对比测试报告了。

### 第二步 深度检索 pss 出清单
检索 `d:\JX3\trunk\sword3-products\trunk\client\data\source\other\` 路径下所有 `.pss`，把绝对路径输出到：
`D:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\logs\ScanFileList.txt`
- 该文件 **GBK 编码、每行 1 个绝对路径 pss 文件名**（中文路径用 GBK，普通文本工具读会 mojibake，属正常）。可读它理解待测范围。

### 第三步 执行 `Jx3LocalResScanTool.cmd`

### 第四步 检查报告完整性
报告在 `d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\logs\JX3\trunk\` 路径下**最新创建的一个子目录**（目录名是时间戳，如 `20260721_173011/`），该子目录下所有文件都是报告内容。

- 检查数据日志,确保进程正常执行完成
  - 文件:Scan.log
  - 最后一行日志类似:17:30:21.866	TID(15708)	INFO	日志正常关闭
- 检查Pss相关数据
  - SQLite3数据库文件:ScanResult.db
  - 数据表:FileList/Result/Pss
  - 音频标签数据库:AudioLabel.db

## 6. 出代码修改前后，对比测试报告

- 保持于：d:\QCBase\trunk\SourceCode\Tool\HDTools\KResourceReader\x64\Release\logs\UpdateCodePss.md
- 报告内容必须包括：
  - 文件:Scan.log
    - 最后一行日志 是否有 `日志正常关闭` 字样，如果没有说明进程(Jx3SvnHookCheckTool.exe)执行失败
  - SQLite3数据：
    - 缺陷检查数据库：ScanResult.db中，表 FileList、Result、Pss内容对比，相同、不同，以及不同的原因。
    - 音频标签数据库：AudioLabel.db中，表 File、FilterKmsc、LogInfo、MovieKrlTxt、NewMovieInfo内容对比，相同、不同，以及不同的原因。

