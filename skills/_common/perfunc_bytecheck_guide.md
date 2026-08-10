# 逐函数字节核对指南(代码同步必做,防已有 case 落后)

> 适用:所有代码同步技能(Pss/kmsc/Ani/tani/krl/SRScene/State)
> 来源:2026-08-07 kmsc `KMovieActionMetaFacePoseAnimation::LoadFromFile` V4/V5 漏检教训(用户复查发现)
> 各技能 SKILL.md §2 比对法末尾均指向本指南。换机器执行任一技能都会用到。

## 1. 问题:case 集合差的盲区

代码同步技能的 §2 比对,通常先做 **case 集合差**(找 switch 缺的 case,如 kmsc `NewAction` 缺 `EAT_Water`)。但这**只能发现"分派层缺新类型"**,发现不了:

> **已有 case 的 per-type `LoadFromFile`/`ReadData` 内部版本分支落后**

即:复刻 switch 里**有**这个 case(集合差不报),但该 case 调用的 `LoadFromFile` 函数体里,`dwVersion` 版本分支只到旧版本,引擎已升新版加了字段,复刻没跟 → 字段错位/漏抽。

### 真实案例(kmsc MetaFacePose)
- 复刻 `Kmsc::NewAction` 有 `case EAT_MetaFacePoseAnimation`(在 107 个 case 里),case 集合差不报它。
- 但 `KMovieActionMetaFacePoseAnimation::LoadFromFile` 只读到 V3,缺引擎 `>=4`(bRestoreMouthFaceMatrix BOOL)、`>=5`(bEnableMouthPlacementCompensation BOOL)。
- 引擎 `SaveToFile` 已写 `dwVersion=5`。
- kmsc 动作块**共享同一 buffer 顺序推进**,末尾少跳 8 字节 → 后续动作块错位 → `NewAction` default 硬失败 → 整个 kmsc 解析失败。
- 本次 baseline 1060 kmsc 0 失败,只因**数据集无 V4/V5 MetaFacePose 文件**(预防性同步);将来产出会失败。

## 2. 必做步骤:逐函数字节核对

做完 case 集合差后,对**每个已有 case** 的 per-type `LoadFromFile`/`ReadData`,逐字节核对与引擎对齐:

1. **找引擎该类型的 `SaveToFile`**,grep 当前写盘版本:
   ```
   grep -nE 's_dwVersion|static.*dwVersion\s*=\s*[0-9]|dwVersion\s*=\s*[0-9]' 引擎Xxx.cpp
   ```
   得该类型**当前最高版本 N**(`s_dwVersion = N` 或 `dwVersion = N` 在 SaveToFile 里)。这是 per-type 落后的**信号源**。

2. **找引擎该类型的 `LoadFromFile`**,核它的版本分支 `if(dwVersion>=N)` / `case N` 覆盖到 SaveToFile 的最高版本。记下每个分支读的字段/字节数。

3. **核复刻同函数**的版本分支:
   - 分支上限是否与引擎一致(复刻最高 `>=M`,引擎最高 `>=N`,`M<N` 则复刻缺 `>=M+1..N` 分支 = 落后)
   - 每段 `Reference`/`SkipData`/`_ReadBuffer` 的**总字节数**与引擎该版本一致(不追求逐字段读取方式相同,复刻可用 `SkipData` 折叠不要的字段,但总字节要对)
   - 字段顺序一致

4. **区分"字节布局分支"与"运行时默认分支"**(同各 SKILL.md §2 顶部说明):
   - 改变读多少字节 = 字节布局分支,**必须对齐**
   - 只改运行时变量值、字节数不变 = 运行时默认分支,复刻跳过即可,不算落后

5. 缺的分支补上:`if(*pdwVersion>=N) SkipData(sizeof(新字段))` 或 `Reference` 读结构,对齐引擎该版本字节。

## 3. "怀疑异常了"打印阈值 = 引擎最高版本 + 1

复刻各 per-type 函数末尾常有:
```cpp
if (KBase::Instance().IsDebugMode() && (*pdwVersion >= X))
    KG_PRINT("%s : Version=0x%X", "怀疑异常了", *pdwVersion);
```
**X = 引擎该类型当前最高版本 + 1**(超过引擎已知最高版本才视为异常)。

- **补了新版本分支后,X 要相应上移**,不是固定值。
- 例:kmsc MetaFacePose 引擎最高 V5,补 V4/V5 分支后,打印阈值从 `>=4` 改为 `>=6`。
- 核对时:若复刻打印阈值 < 引擎最高版本+1,说明复刻漏了分支(把正常版本当异常了)或阈值没跟上移。

### 超界报错:kmsc 用 OnErrorByGBK 报 TOOL_ERR(不静默打印,2026-08-10 定)

**kmsc 专有约定**(其它技能见各自 SKILL.md):版本超界时**不写静默 `KG_PRINT("怀疑异常了")`**,改为显式 `OnErrorByGBK` 报工具错误——进 Result 表可统计,但**不中断解析**(`bResult=true` 照常)。标准写法:
```cpp
if ((*pdwVersion >= <引擎最高版本+1>))
{
    m_pReadFileBase->OnErrorByGBK(ErrorLevel::ERROR_LEVEL_TOOL_ERR, ErrorType::ERROR_TYPE_TOOL_ERR, "%s:%d\t异常了.怀疑协议有调整", __FUNCTION__, __LINE__);
}
```
- `ErrorType::ERROR_TYPE_TOOL_ERR`(工具错误,勿用 FILESIZE_0);Msg 带 `__FUNCTION__, __LINE__` 定位具体超界点。
- **三种形式都改**①③:①`if(IsDebugMode && >=X)KG_PRINT` 改 `if(>=X){OnErrorByGBK}` **不中断**(无 KG_PROCESS_ERROR);③三元同①;②switch `default: if(IsDebugMode){KG_PRINT} KG_PROCESS_ERROR(false)` 改 `default: OnErrorByGBK(...) KG_PROCESS_ERROR(false)`——**保留 KG_PROCESS_ERROR**(default 是复刻没处理该版本,buffer 没推进,必须失败,OnErrorByGBK 只加可统计标记)。④无阈值无条件非 default 的纯调试打印不改。
- 详见 `kmsc代码同步/SKILL.md` §2.5"超界报错约定"。2026-08-10 已统一 KMovieObject.cpp ①③ 共 32 处 + ② 19 处。

## 4. 常量值存疑:查编辑器 C# 枚举确证

复刻 per-type 用到的常量(如 `EMPA_COUNT`、各类 `_COUNT`、`_Type_Count`)若与引擎注释不符或找不到定义:

- **cpp 注释可能过时**(如 kmsc 引擎 cpp 注释 `EMPA_COUNT //200`,实际 202)。
- 去引擎编辑器 AutoGenCode 的 **C# 枚举**确证:
  ```
  grep -rln 'enum EnumXxxType' $JX3ENGINE_Sword3/Source/KG3DEngineDX11/Tools/MovieEditor/MovieEditor/AutoGenCode/
  ```
  数该枚举的项数(不含 COUNT 哨兵)= COUNT 值。C# 枚举末项 = 项数,是编译期常量,最准。
- 不要轻信 cpp 行内注释,以枚举项数为准。

## 5. 数据集 vs 错位判定(预防性同步的验证)

- 含错位/落后分支的文件若**数据集没有** → 全量 0 失败(预防性同步),diff 零回归 = 对齐验证通过(没碰不该碰的)。
- 若**数据集有** → 硬失败/依赖错位暴露(出现在 baseline 的 still_failing/failed)。
- **"baseline 0 失败" ≠ "无落后"**:数据集未触发的不代表对齐,必须逐函数字节核对才能发现;改码后全量 diff 零回归 = 对齐正确。
- 改码后:用 baseline 同清单跑 current,diff_*.py 对比,`changed/appeared/disappeared/new_fail` 全 0 = 零回归(预防性同步的通过判据)。

## 6. 适用范围(逐函数核对的对象)

| 技能 | 逐函数核对的对象 |
|---|---|
| Pss | 各发射器 `KG3D_ParticleXxxLauncher_ReadData`、各模块 `KG3D_ParticleModule_ReadData` 的版本分支 |
| kmsc | 107 个动作 `KMovieActionXxx::LoadFromFile` 的 `dwVersion` 分支(`s_dwVersion` 信号源在各自 SaveToFile) |
| Ani | ① `Ani::ReadFile` 的 mask 分支;② `KG3D_Animation::ReadFile` 的 dwType/mask 分支 |
| tani | 6 标签 `SFX/Sound/Motion/CameraAni/Texture/ForceField` 的 `LoadFromFile` 的 `dwVersion` 分支 |
| krl | V0-V5 各 `LoadUnitFromBufferV*` 的结构布局(无 dwVersion 分支,核结构字段/pack/sizeof) |
| SRScene | `KSREntity::LoadFromFile` 的 `dwVersion` 分支(>=1/>=2/>=3...) |
| State | `KState_Load`/`_LoadState` 的 `dwVersion` 分支(>=0x01..0x04...) |

每类的"信号源":引擎 SaveToFile 的当前写盘版本(`s_dwVersion` 或 `dwVersion=N`)。

## 7. 相关

- 同步技能总规律:CodeReview.md / 各 SKILL.md §2
- 版本分支层同步模式:`feedback_version_branch_sync`
- 换机器重编 RUST 的 build.sh 路径 bug:`project_buildsh_rust_path_bug`
