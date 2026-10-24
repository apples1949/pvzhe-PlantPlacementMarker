# 种植位置标识（PlantPlacementMarker） v2.0.0

选中卡牌时，在**所有可种植的格子**上显示标识；另有一种「整行整列」的十字准星样式。
游戏版本：PVZ 杂交重制版 0.31.0（Godot 4 + C#，Mod API v3）

## 功能

| 项 | 说明 |
|---|---|
| 触发 | 选卡栏选中任意卡牌 → 场上所有能种的位置立刻出现标识；松手/取消 → 立刻消失 |
| 样式 ① | **圆圈 + 十字**：圆环反复放大缩小（0.17→0.28 格宽），十字固定 |
| 样式 ② | **四角 + 十字**：四个角标沿对角线向中心来回移动（0~8% 格宽），十字固定 |
| 样式 ③ | **整行整列**：以鼠标所在格为交点，横向 + 纵向各一条色带（十字准星），交点可选画十字 |
| 粗细 | 4 档预设：细 / 标准 / 粗 / 极粗（① ② 控制描边宽度，③ 控制色带宽度） |
| 颜色 | 三种样式共用的颜色（默认纯白） |
| 中心十字 | 独立开关，关掉只留圆环/四角/色带 |

配置位置：**选项 → Mod 管理 → 种植位置标识 → 配置**（全部 `applyMode=immediate`，改完立即生效，不用重启）。

## ★ v2.0.0：为什么重写绘制层（v1.x「装上了完全没效果」的根因）

本 Mod 的程序集**不引 Godot.NET.Sdk**（无源码生成器）⇒ 程序集里自定义的 `Node` 子类
**不会收到引擎的 `_Process`/`_Draw` 回调**：节点挂得上、什么都不画、一行日志都没有。
v1.x 正是踩了这个坑（用户实测"压根没效果"）。

v2.0.0 改为 **RenderingServer 画布项**：
`process_frame` 回调驱动 → `CanvasItemCreate` 拿 RID → 挂到 `mapControl.spriteNode.GetCanvasItem()` →
每帧 `CanvasItemClear` + `AddLine / AddPolyline / AddRect`。这是同工程其它 Mod 唯一验证过的驱动方式。

实机日志（v2.0.0 实测，启动即出）：
```
[PlantPlacementMarker] 入口已加载 v2.0.0；process_frame 连接=OK；样式=CircleCross 颜色=ffffffff 中心十字=True
[PlantPlacementMarker] 帧回调已开始运行
[PlantPlacementMarker] 绘制画布已挂到 spriteNode        ← 进战斗后出现
[PlantPlacementMarker] 首次显示：样式=… 可种格=N …      ← 第一次真的画出来时出现
```

## 实现方式（单个画布项，性能优先）

* 只有 **1 个 RenderingServer 画布项（RID）**，父级是 `TowerDefenseMapControl.spriteNode` 的画布项，
  全部图形用 `CanvasItemAddLine / AddPolyline / AddRect` **程序化绘制**。
* **不吃贴图、不用序列帧、不按格挂节点**：45 格同时显示也只有 1 个节点、1 次 draw batch。
* 可放置判定用游戏自己的 `TowerDefenseCellInstance.CanPacketPlant(config)`，
  与玩家真点下去时的判定**完全同源**（含墓碑/藤架/飞行植物等特例）。
* 判定结果**节流 0.15s 缓存**（悬停格变化时立即重算），每帧只做绘制，
  避免每帧 45 次 `CanPacketPlant`。
* 坐标：绘制统一用**地图世界坐标**，每帧把节点 Transform 对齐成
  `A = spriteNode.globalT⁻¹ · canvasT`，所以相机缩放/平移、编辑器 0.85 缩放都自动跟随，任意分辨率不糊。

## 位置校准（v2.6.x，实测流程）

**锚点公式**（与游戏取格同源）：
```
x = gridBeginPos.X + (col - 0.5) * gridSize.X
y = gridBeginPos.Y + (row - 0.5) * gridSize.Y - curve.Sample(0.5)   // 无曲线时 curve 项为 0
最终位置 = (x + offsetX, y + offsetY)
```

**怎么量出 offsetY**（用玩家截图反推，不用猜）：
1. 从截图里提取标识的行中心（白色像素按 y 聚簇）→ 得到行间距 = `gridSize.Y × 缩放`；
2. 用同一缩放把草坪/水池的可见带边界换算成行中心；
3. 两者差值的平均值 ÷ 缩放 = 世界像素偏移。
   实测 Backyard（9×6，格 78×85，夜）：行间距 127.5px ⇒ 缩放 1.5；差值平均 −24px ⇒ **−16 世界像素**，即标识偏高 16px ⇒ `offsetY = 16`。
4. 注意：本图美术行高本就不均匀（草地行 ≈123px、水池行 ≈135px），统一 gridSize 无法逐行完美，
   所以留了 `offsetX / offsetY` 两个微调项给玩家自行校正。

## 已修复的实机 bug（v2.8.x）

| 现象 | 根因 | 修法 |
|---|---|---|
| 暂停（ESC 菜单）后仍选着卡时，标识继续跟随鼠标 | `process_frame` 不看暂停；游戏暂停用的是 `currentControl.waitPause` + `SceneTree.Paused`，不是引擎暂停 | 两个判据都检查，暂停即隐藏（`Hide()` + 清缓存） |
| **颜色设置无效** | 宿主把 `color` 归一化成 **`Godot.Color`** 对象（`XWModSettingsService: normalized = new Color("#"+ToHtml())`），旧代码只按字符串解析 ⇒ 永远回落到白色 | `ReadColor` 支持 `Color` / `Variant(Color)` / string / JsonElement |

## 新增配置

- **在超级大地图也生效**（`allowSuperBigMap`，默认开）：格子总数 > 100 视为超大地图（27×15=405 算；9×6=54、11×7=77 不算），关掉后在这类图上不显示。

## 实机验证状态（2026-10-24）

| 功能 | 证据 |
|---|---|
| 三样式都能画 | 玩家实机截图：**圆圈+十字** ✓、**四角+十字** ✓；日志 `首次显示（整行整列）` ⇒ **整行整列** ✓ |
| 配置项 | 样式/粗细/颜色/中心十字/倍率/微调 均在配置页即时生效 |
| 打包装机 | `check_gates.py` 9/9（含构建指纹），pmod 与装机包哈希一致 |
| 未闭环 | **纵向位置**：Backyard 系列图的美术行高（≈91px）与配置 `gridSize.Y`(85) 略有差异，统一网格无法逐行完全贴合 ⇒ 用 `纵向微调` 补偿（默认 16），玩家可自行微调 |

### 位置偏差的定量结论（2026-10-24 用玩家截图逐行反推）

把截图里的标识行中心 + 草坪/水池带边界一起换算回世界坐标：

| 行 | 美术反推行顶（世界） | 均匀网格 60+85i | 差 |
|---|---|---|---|
| 1 | 60.0 | 60 | 0 |
| 2 | 142.3 | 145 | −2.7 |
| 3 | 224.7 | 230 | −5.3 |
| 4 | 315.0 | 315 | 0 |
| 5 | 405.3 | 400 | +5.3 |
| 6 | 487.7 | 485 | +2.7 |

⇒ **美术行距就是均匀的 `gridSize.Y`**（之前的"行高不均"判断是错的，已纠正），
而标识整行整列地比美术低/高一个**常数**：截图里标识比带中心高 24.25 图像像素
（缩放 1.5）⇒ **−16 世界像素**。所以修法是常数补偿 `offsetY = 16`，不是改行距；
`行高倍率` 仅留给确实非均匀的自制图。

## 目录

```
PlantPlacementMarker/
├── mod.json                      # 清单 + 9 个配置项（已过宿主 ValidateDefinitions）
├── runtime_src/
│   ├── PlantPlacementMarker.csproj
│   ├── PlantPlacementMarkerEntry.cs   # 入口 + MarkerPainter（全部绘制逻辑）
│   └── bin/Release/JTYPlantPlacementMarker.dll
├── Runtime/ModAssembly.dll       # 打包用（= 上面 DLL 改名，md5 必须一致）
├── dist/PlantPlacementMarker.pmod
├── build_and_install.py          # 编译 → 打包 → 装机（--install）
├── build_pmod.py                 # 仅打包（含护栏校验）
└── tools/preview_marker.py       # 离线预览三种样式的实际比例（不改游戏）
```

## 构建 / 装机

```powershell
cd mods\PlantPlacementMarker
python build_and_install.py            # 只编译
python build_and_install.py --install  # 编译 + 打包 + 装机 + 清 ModsCache/PlantPlacementMarker
```

装机目标：`%APPDATA%\Godot\app_userdata\植物大战僵尸杂交版\Mods\PlantPlacementMarker.pmod`
（本机已把 `plantplacementmarker` 写进 `Mods/enabled_mods.json`，重启游戏即生效）

## 离线预览（不用开游戏）

```powershell
python tools\preview_marker.py       # 9x5 标准草坪色块上的三种样式（10 张）
python tools\preview_on_map.py       # 画到**真实地图贴图**上，验证格子基准（3 张）
```

`preview_on_map.py` 用的是真实地图数据
（`FrontlawnMapFrontlawn.tres`：`gridBeginPos=(260,75)`、`gridSize=(80,98)`、`gridNum=9x5`），
青色网格线与草坪 9 列 5 行的实际边界**完全重合** ⇒ 说明代码里
`gridBeginPos + ((x-1)*gridSize)` 这套格子基准是对的（2026-10-23 已核对）。

两个预览脚本里的比例常量与 `PlantPlacementMarkerEntry.cs` 由 `tools\check_gates.py` 第 8 项
**逐条比对**，改代码不同步改预览会直接 FAIL。

## 已知边界

* 标识只按「当前卡牌能否种在这一格」显示，**不预测**未来（例如阳光不足时仍会显示）。
* 整行整列样式**必须**有鼠标悬停格才显示（手机端靠 Godot 的模拟鼠标位置）。
* 目前不支持「只显示鼠标所在格」的收敛模式；如需可加一个「只标当前格」开关。

## 验证记录（2026-10-23，v1.0.x）

离线闸门 `python tools\check_gates.py` —— 9 项全过（v1.0.5 实测）：
```
1 mod.json 合法（9 配置项 / 2 下拉）      5 宿主 ValidateDefinitions 通过
2 Runtime/ 只含 ModAssembly.dll          6 enabled_mods.json 含 plantplacementmarker
3 编译产物 == Runtime DLL（d8cb54e3…）    7 DLL 关键符号 9 项齐全
4 pmod 结构正确且与装机包一致（12087 B）   8 两份预览 15 条比例常量与 C# 一致
9 构建指纹匹配（源码 → 产物，v1.0.5）
```

实机加载验证（启动游戏读 `logs\godot.log`，验证后已关闭并清理 journal）：
```
[ModLoader] package extracted safely: plantplacementmarker (1 files)
[ModLoader] package applied: plantplacementmarker; resources=0; runtimeEntry=True; callbacks=0; diagnostics=0
[ModManager] enabled runtime apply complete: 17/17; rollbackBlocked=False; safeMode=False
```
日志内 `ERROR|Exception` 命中 0 条。

**尚未验证**：视觉观感（位置/大小/层级/动效）需人工进关看点卡后的表现。

v1.0.1 追加：`_Process` / `_Draw` 的异常不再静默 —— 任何异常都会用 `GD.PushWarning` 打一条
`[PlantPlacementMarker] _Draw 异常…`（只打一次），这是"标识完全不出"时最直接的线索。

### ⚠️ 闸门第 9 项（2026-10-24 补）：防止"闸门替旧包背书"

本轮真实踩到：改源码写错一个字段 → `dotnet build` **失败** → 旧 DLL 原封不动留在 `Runtime/`，
而 1~8 项（含"编译产物 == Runtime DLL"）**全部照样绿** —— 因为比的是"两个旧文件彼此一致"。
现在 `build_and_install.py` 编译成功后会写 `runtime_src/build_stamp.json`（源码 sha256 + 产物哈希 + 版本），
`check_gates` 第 9 项据此判"产物到底是不是这份源码编的"。
负向测试：给 .cs 追加一行注释 → 第 9 项立刻 FAIL（已实测）；还原后又 PASS。

v1.0.5 每次启动后第一次真正画出标识时，无条件打印
`[PlantPlacementMarker] 首次显示：样式/可种格/网格/格尺寸/原点/颜色`（不依赖诊断开关）。

v1.0.4 新增诊断开关「自动截图」(`debugScreenshot`)：
标识连续可见 1.2s 后 `RenderingServer.ForceDraw()` + 视口取图存成
`user://PlantPlacementMarker_shot.png`，并把**绝对路径**打进 godot.log。
好处：用户只要进一次关，我就能直接看到实机画面（不用人工描述或截图）。

v1.0.3 新增诊断开关「不选卡也画全部格子」（`debugShowGrid`，默认关）：
打开后未选卡也会按当前样式画满全场，用来把问题一分为二 ——
**能画出来=渲染/坐标/层级都对，问题在选卡判定**；**画不出来=渲染链路有问题**。

v1.0.2 修复：地图 `lineUse` 数组为空时，`GetMapLineUse()` 对越界**返回 false**，
原实现把所有行都当成"不可用" ⇒ 一个标识都不画（且无报错）。现改为**数组没覆盖 1..gridNum.Y 就跳过该过滤**，
并把"行过滤=启用/跳过"写进诊断日志。

⚠️ 开发期注意：**不要用"截图 + 模拟点击"自动驱动游戏**。本机实测 `SetForegroundWindow`
拉不起后台窗口，`CopyFromScreen` 抓到的是前台那个程序（当时是 L4D2）⇒ 点击会落到别人窗口里。
实机验证只能人工做。
若标识位置不对或不出，把配置页「输出诊断日志」打开再选卡，日志会打印一行：
`[PlantPlacementMarker] 开始显示：样式=… 可种格=… 网格=… 格尺寸=(80,98) 原点=…`
拿这行就能判定是坐标基准问题还是判定问题。
