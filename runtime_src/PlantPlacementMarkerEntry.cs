// ============================================================================
//  种植位置标识 v2.0.0 —— 纯 RenderingServer 实现（不再自定义 Node 子类）
//
//  ⛔ 为什么不写 `class X : Node2D` + 重写 _Draw/_Process：
//     本工程刻意不引 Godot.NET.Sdk（无源码生成器 ⇒ 没有脚本桥注册）。
//     这种程序集里自定义的 Node 子类，**引擎不会回调它的 _Process/_Draw**，
//     表现就是"节点挂上了、什么都不画、日志一行没有"（v1.x 实测踩到）。
//     ⇒ 改用 RenderingServer 的 canvas_item RID，由入口的 process_frame 回调驱动；
//        这也是同工程其它 Mod 唯一验证过的驱动方式。
//
//  几何（1000 单位制设计稿 → 按格子尺寸等比缩放）：
//    ① 圆圈+十字：圆环 r 170↔280、十字半长 119、线宽 15
//    ② 四角+十字：方框 158..842、圆角 70、臂长 140、内移 0↔80
//    ③ 整行整列：以悬停格为中心的横/竖色带
//
//  用到的公开 API（全部编译期校验，无反射）：
//    TowerDefenseManager.Instance / .gridSize / .gridBeginPos / .gridNum / .currentControl
//    TowerDefenseManager.GetMapFeature() / .GetMapCell() / .GetMapGridPosFromMouse() / .GetMapLineUseArr()
//    TowerDefenseBattleFeatureMap.mapControl / .packetPickControl
//    PacketPickControl.IsPicking() / .packetPick
//    TowerDefenseMapControl.spriteNode / .GetCanvasTransform()
//    TowerDefenseCellInstance.CanPacketPlant(config)
//    RenderingServer.CanvasItem*（Create/Clear/SetParent/SetTransform/SetVisible/
//                   SetZIndex/SetZAsRelative/AddLine/AddCircle/AddRect/AddPolyline/FreeRid）
// ============================================================================
using System;
using System.Collections.Generic;
using Godot;
using PVZHE.ModEditor.ModSystem;

// ============================================================================
//  配置模型
// ============================================================================
public enum MarkerStyle
{
	CircleCross = 0,
	CornersCross = 1,
	RowColumn = 2
}

public enum MarkerThickness
{
	Thin = 0,
	Normal = 1,
	Thick = 2,
	XLarge = 3
}

public struct MarkerSettings
{
	public bool Enabled;
	public MarkerStyle Style;
	public bool ShowCross;
	public MarkerThickness Thickness;
	public Color Tint;
	public bool DebugShowGrid;
	public bool DebugScreenshot;
	public bool DebugSmoke;      // 诊断：不进战斗也在屏幕中央画一个测试标记（验证渲染链路）
	public float Scale;          // 标识整体尺寸倍率（0.5~2.0）
	public float OffsetX;        // 位置微调（世界像素，向右为正）
	public float OffsetY;        // 位置微调（世界像素，向下为正）
	public float RowPitchScale;  // 行高倍率：修正「美术行高 ≠ gridSize.Y」导致的下行漂移
	public bool AllowSuperBigMap; // 是否在超级大地图（如 27x15）上也生效

	public static MarkerSettings Default()
	{
		return new MarkerSettings
		{
			Enabled = true,
			Style = MarkerStyle.CircleCross,
			ShowCross = true,
			Thickness = MarkerThickness.Normal,
			Tint = new Color(1f, 1f, 1f, 1f),
			DebugShowGrid = false,
			DebugScreenshot = false,
			DebugSmoke = false,
			Scale = 1f,
			OffsetX = 0f,
			OffsetY = 16f,
			RowPitchScale = 1f,
			AllowSuperBigMap = true
		};
	}

	public float StrokeWidth
	{
		get
		{
			switch (Thickness)
			{
				case MarkerThickness.Thin: return 2.0f;
				case MarkerThickness.Thick: return 4.5f;
				case MarkerThickness.XLarge: return 6.5f;
				default: return 3.0f;
			}
		}
	}

	public float BandWidth
	{
		get
		{
			switch (Thickness)
			{
				case MarkerThickness.Thin: return 14f;
				case MarkerThickness.Thick: return 32f;
				case MarkerThickness.XLarge: return 46f;
				default: return 22f;
			}
		}
	}
}

// ============================================================================
//  运行时入口
// ============================================================================
public sealed class PlantPlacementMarkerEntry : IXWModRuntimeEntry
{
	internal const string LogPrefix = "[PlantPlacementMarker] ";
	internal const string BuildTag = "v2.8.1";

	private XWModRuntimeContext _context;
	private SceneTree _tree;
	private Callable _tickCallable;
	private bool _tickConnected;
	private bool _settingsSubscribed;

	internal static bool FirstShowLogged;
	internal static MarkerSettings Settings = MarkerSettings.Default();
	internal static bool EnableLog;
	internal static XWModRuntimeContext PluginContext;

	public void Initialize(XWModRuntimeContext context)
	{
		try
		{
			_context = context;
			PluginContext = context;
			ReloadSettings();

			try
			{
				if (context?.Settings != null && !_settingsSubscribed)
				{
					context.Settings.Changed += OnSettingsChanged;
					_settingsSubscribed = true;
				}
			}
			catch { }

			string connectState = "未连接";
			try
			{
				_tree = Engine.GetMainLoop() as SceneTree;
				if (_tree == null)
				{
					connectState = "SceneTree 取不到";
				}
				else if (!_tickConnected)
				{
					_tickCallable = Callable.From(new Action(OnFrame));
					_tree.Connect("process_frame", _tickCallable);
					_tickConnected = true;
					connectState = "OK";
				}
				else
				{
					connectState = "已连接";
				}
			}
			catch (Exception e)
			{
				connectState = "异常：" + e.Message;
			}

			// ★ 无条件打一行：这是"Mod 到底有没有跑起来"的第一现场证据
			SelfTest();
			GD.Print(LogPrefix + "入口已加载 " + BuildTag + "；process_frame 连接=" + connectState +
			         "；样式=" + Settings.Style + " 颜色=" + Settings.Tint.ToHtml() +
			         " 中心十字=" + Settings.ShowCross);
		}
		catch (Exception e)
		{
			try { GD.PushWarning(LogPrefix + "Initialize 异常（已吞）：" + e.Message); } catch { }
		}
	}

	/// <summary>启动自检：三种样式的几何构建各空跑一遍（不碰渲染），启动即暴露"某个样式必崩"的问题。</summary>
	private static void SelfTest()
	{
		try
		{
			Vector2 cell = new Vector2(80f, 98f);
			float unit = Math.Min(cell.X, cell.Y);
			float[] phases = { 0f, 0.5f, 1f };
			string msg = "";
			foreach (float p in phases)
			{
				var ring = MarkerPainter.BuildRingPoints(Vector2.Zero, unit * (0.17f + 0.11f * p), 40);
				var lines = new System.Collections.Generic.List<Vector2[]>(4);
				var stems = new System.Collections.Generic.List<Vector2[]>(4);
				MarkerPainter.BuildCorners(Vector2.Zero, cell, unit, p, lines, stems);
				if (ring.Length != 41 || lines.Count != 4 || stems.Count != 4)
				{
					msg += " 几何数量异常(p=" + p + ")";
				}
			}
			GD.Print(LogPrefix + "自检：" + (msg.Length == 0 ? "圆圈/四角几何 OK（3 个相位各跑一遍）" : msg));
		}
		catch (Exception e)
		{
			try { GD.PushWarning(LogPrefix + "自检异常（某样式可能画不出来）：" + e.Message); } catch { }
		}
	}

	public void OnAllModsLoaded()
	{
		try { ReloadSettings(); } catch { }
	}

	public void Shutdown()
	{
		try
		{
			if (_context?.Settings != null && _settingsSubscribed)
			{
				_context.Settings.Changed -= OnSettingsChanged;
				_settingsSubscribed = false;
			}
		}
		catch { }
		try
		{
			if (_tree != null && _tickConnected)
			{
				_tree.Disconnect("process_frame", _tickCallable);
				_tickConnected = false;
			}
		}
		catch { }
		try { MarkerPainter.Destroy(); } catch { }
	}

	private static bool _frameLogged;
	private static bool _frameErrorLogged;

	private void OnFrame()
	{
		try
		{
			if (!_frameLogged)
			{
				_frameLogged = true;
				GD.Print(LogPrefix + "帧回调已开始运行");
			}
			MarkerPainter.Tick(Settings);
		}
		catch (Exception e)
		{
			if (!_frameErrorLogged)
			{
				_frameErrorLogged = true;
				try { GD.PushWarning(LogPrefix + "帧回调异常（已捕获，标识不会显示）：" + e); } catch { }
			}
		}
	}

	private void OnSettingsChanged(IReadOnlyList<string> keys)
	{
		try { ReloadSettings(); } catch { }
	}

	internal static void ReloadSettings()
	{
		XWModRuntimeContext ctx = PluginContext;
		if (ctx == null) { return; }

		MarkerSettings s = MarkerSettings.Default();
		s.Enabled = ReadBool(ctx, "enabled", true);
		s.Style = ReadStyle(ctx, "style", MarkerStyle.CircleCross);
		s.ShowCross = ReadBool(ctx, "showCenterCross", true);
		s.Thickness = ReadThickness(ctx, "thickness", MarkerThickness.Normal);
		s.Tint = ReadColor(ctx, "color", new Color(1f, 1f, 1f, 1f));
		s.DebugShowGrid = ReadBool(ctx, "debugShowGrid", false);
		s.DebugScreenshot = ReadBool(ctx, "debugScreenshot", false);
		s.DebugSmoke = ReadBool(ctx, "debugSmoke", false);
		s.Scale = ReadFloat(ctx, "markerScale", 1f);
		s.OffsetX = ReadFloat(ctx, "offsetX", 0f);
		s.OffsetY = ReadFloat(ctx, "offsetY", 16f);
		s.RowPitchScale = ReadFloat(ctx, "rowPitchScale", 1f);
		s.AllowSuperBigMap = ReadBool(ctx, "allowSuperBigMap", true);
		EnableLog = ReadBool(ctx, "enableLog", false);
		Settings = s;
	}

	internal static void Info(string msg)
	{
		if (!EnableLog) { return; }
		try { GD.Print(LogPrefix + msg); } catch { }
	}

	private static bool ReadBool(XWModRuntimeContext ctx, string key, bool def)
	{
		try
		{
			object v = ctx.Settings.Get<object>(key);
			if (v is bool b) { return b; }
			if (v is string s && bool.TryParse(s, out bool sb)) { return sb; }
			if (v is System.Text.Json.JsonElement je)
			{
				if (je.ValueKind == System.Text.Json.JsonValueKind.True) { return true; }
				if (je.ValueKind == System.Text.Json.JsonValueKind.False) { return false; }
			}
		}
		catch { }
		return def;
	}

	private static string ReadString(XWModRuntimeContext ctx, string key, string def)
	{
		try
		{
			object v = ctx.Settings.Get<object>(key);
			if (v is string s && s.Length > 0) { return s.Trim(); }
			if (v is System.Text.Json.JsonElement je &&
			    je.ValueKind == System.Text.Json.JsonValueKind.String)
			{
				return (je.GetString() ?? "").Trim();
			}
		}
		catch { }
		return def;
	}

	private static MarkerStyle ReadStyle(XWModRuntimeContext ctx, string key, MarkerStyle def)
	{
		switch (ReadString(ctx, key, "").ToLowerInvariant())
		{
			case "circle": return MarkerStyle.CircleCross;
			case "corners": return MarkerStyle.CornersCross;
			case "rowcol": return MarkerStyle.RowColumn;
		}
		return def;
	}

	private static MarkerThickness ReadThickness(XWModRuntimeContext ctx, string key, MarkerThickness def)
	{
		switch (ReadString(ctx, key, "").ToLowerInvariant())
		{
			case "thin": return MarkerThickness.Thin;
			case "normal": return MarkerThickness.Normal;
			case "thick": return MarkerThickness.Thick;
			case "xlarge": return MarkerThickness.XLarge;
		}
		return def;
	}

	private static float ReadFloat(XWModRuntimeContext ctx, string key, float def)
	{
		try
		{
			object v = ctx.Settings.Get<object>(key);
			if (v is float f) { return f; }
			if (v is double d) { return (float)d; }
			if (v is int i) { return i; }
			if (v is string s && float.TryParse(s, System.Globalization.NumberStyles.Float,
			        System.Globalization.CultureInfo.InvariantCulture, out float sf)) { return sf; }
			if (v is System.Text.Json.JsonElement je && je.ValueKind == System.Text.Json.JsonValueKind.Number)
			{
				return (float)je.GetDouble();
			}
		}
		catch { }
		return def;
	}

	private static Color ReadColor(XWModRuntimeContext ctx, string key, Color def)
	{
		try
		{
			object v = ctx.Settings.Get<object>(key);
			// ★ 宿主把 color 归一化成 Godot.Color（XWModSettingsService: normalized = new Color("#"+ToHtml())），
			//   旧代码只按 string 解析 ⇒ 永远读不到 ⇒ 玩家改颜色"没效果"（bug 根因）。
			if (v is Color c) { return c; }
			if (v is Variant vv)
			{
				switch (vv.VariantType)
				{
					case Variant.Type.Color: return vv.AsColor();
					case Variant.Type.String: v = vv.AsString(); break;
				}
			}
			string raw = v as string;
			if (raw != null && (raw.Length == 7 || raw.Length == 9) && raw[0] == '#')
			{
				try { return new Color(raw); } catch { }
			}
			if (v is System.Text.Json.JsonElement je &&
			    je.ValueKind == System.Text.Json.JsonValueKind.String)
			{
				string js = (je.GetString() ?? "").Trim();
				if ((js.Length == 7 || js.Length == 9) && js[0] == '#')
				{
					try { return new Color(js); } catch { }
				}
			}
		}
		catch { }
		return def;
	}
}

// ============================================================================
//  绘制器：纯 C# 类，不继承任何 Godot 类型；用 RenderingServer 的 canvas_item RID
// ============================================================================
internal static class MarkerPainter
{
	private const float PulsePeriod = 1.6f;
	private const float CellRefreshInterval = 0.15f;
	private const int ZIndexValue = 3500;

	private static Rid _rid;
	private static Node2D _host;
	private static Node2D _smokeHolder;
	private static bool _attachedLogged;
	private static bool _errorLogged;

	private static double _pulse;
	private static double _cellTimer = 999.0;
	private static double _visibleTime;
	private static bool _shotDone;
	private static bool _loggedShow;
	private static bool _loggedDebug;
	private static bool _linesGated = true;
	private static double _lastClock;

	private static readonly List<Vector2I> _cells = new List<Vector2I>();
	private static bool _haveHover;
	private static Vector2I _hover;
	private static Vector2I _lastHover = new Vector2I(-999, -999);
	private static bool _hoverPlantable;
	private static bool _visible;

	// ------------------------------------------------------------------ 主循环
	public static void Tick(MarkerSettings cfg)
	{
		double now = Time.GetTicksMsec() / 1000.0;
		double delta = (_lastClock <= 0.0) ? 0.016 : Math.Min(0.1, Math.Max(0.0, now - _lastClock));
		_lastClock = now;

		if (!cfg.Enabled)
		{
			Hide();
			return;
		}

		TowerDefenseManager mgr = TowerDefenseManager.Instance;
		bool battleReady = GodotObject.IsInstanceValid(mgr) && IsBattleScene(mgr);

		// ★ 暂停时一律不显示（玩家实测 bug：按 ESC 进暂停菜单后，若还选着卡，
		//   标识会继续跟着鼠标走）。两个判据都要看：
		//   ① SceneTree.Paused —— 引擎级暂停；
		//   ② currentControl.waitPause —— 游戏自己的暂停菜单标记
		//      （TowerDefenseControlNew.OpenGamePauseDialog() 里置 true、关窗置 false）。
		bool paused = false;
		if (battleReady)
		{
			try
			{
				SceneTree tree = Engine.GetMainLoop() as SceneTree;
				if (tree != null && tree.Paused) { paused = true; }
				if (!paused)
				{
					TowerDefenseControlNew ctl = mgr.currentControl;
					if (GodotObject.IsInstanceValid(ctl) && ctl.waitPause) { paused = true; }
				}
			}
			catch { }
		}
		if (paused)
		{
			_cells.Clear();
			Hide();
			return;
		}

		if (!battleReady)
		{
			if (cfg.DebugSmoke) { DrawSmoke(cfg, delta); }
			else { Hide(); }
			return;
		}

		// 超级大地图（27x15 之类）可由配置关闭
		if (!cfg.AllowSuperBigMap && IsSuperBigMap(mgr))
		{
			_cells.Clear();
			Hide();
			return;
		}

		TowerDefenseBattleFeatureMap mf = TowerDefenseManager.GetMapFeature();
		if (!GodotObject.IsInstanceValid(mf) || !GodotObject.IsInstanceValid(mf.mapControl) ||
		    !GodotObject.IsInstanceValid(mf.mapControl.spriteNode))
		{
			Hide();
			return;
		}

		Node2D host = mf.mapControl.spriteNode;
		if (!EnsureRid(host))
		{
			Hide();
			return;
		}

		if (!_attachedLogged)
		{
			_attachedLogged = true;
			GD.Print(PlantPlacementMarkerEntry.LogPrefix + "绘制画布已挂到 spriteNode");
		}

		_pulse += delta;
		_cellTimer += delta;

		PacketPickControl pick = mf.packetPickControl;
		bool picking = GodotObject.IsInstanceValid(pick) && pick.IsPicking();
		TowerDefenseInGamePacketShow packet = picking ? pick.packetPick : null;
		TowerDefensePacketConfig packetConfig =
			(picking && GodotObject.IsInstanceValid(packet)) ? packet.config : null;

		// ---- 没选卡 ----
		if (packetConfig == null)
		{
			if (cfg.DebugShowGrid)
			{
				if (_cells.Count == 0 || _cellTimer >= CellRefreshInterval)
				{
					_cellTimer = 0.0;
					RebuildAllCells(mgr);
				}
				if (!_loggedDebug)
				{
					_loggedDebug = true;
					GD.Print(PlantPlacementMarkerEntry.LogPrefix + "调试模式：未选卡也画全部格子（格数=" +
					         _cells.Count + " 网格=" + mgr.gridNum.X + "x" + mgr.gridNum.Y +
					         " 格尺寸=(" + mgr.gridSize.X + "," + mgr.gridSize.Y + ") 原点=(" +
					         mgr.gridBeginPos.X + "," + mgr.gridBeginPos.Y + ")）");
				}
				_visible = _cells.Count > 0;
				Draw(cfg, mgr, mf.mapControl.mapNode, mf.config, delta);
				return;
			}
			_cells.Clear();
			_haveHover = false;
			_hoverPlantable = false;
			_lastHover = new Vector2I(-999, -999);
			_cellTimer = 999.0;
			_loggedShow = false;
			_loggedDebug = false;
			Hide();
			return;
		}

		// ---- 悬停格 ----
		Vector2 world = GetMouseWorld(mf.mapControl);
		Vector2I hover = mgr.GetMapGridPosFromMouse(world);
		bool hoverIn = mgr.CheckMapGridPosIn(hover);
		bool hoverChanged = hoverIn && (!_haveHover || hover != _lastHover);
		_haveHover = hoverIn;
		if (hoverIn) { _hover = hover; _lastHover = hover; }

		bool needRefresh = hoverChanged || _cellTimer >= CellRefreshInterval;

		// ---- 整行整列 ----
		if (cfg.Style == MarkerStyle.RowColumn)
		{
			_cells.Clear();
			if (!hoverIn)
			{
				_hoverPlantable = false;
			}
			else if (needRefresh)
			{
				_cellTimer = 0.0;
				TowerDefenseCellInstance hc = TowerDefenseManager.GetMapCell(hover);
				try { _hoverPlantable = GodotObject.IsInstanceValid(hc) && hc.CanPacketPlant(packetConfig); }
				catch { _hoverPlantable = false; }
			}
			_visible = hoverIn && _hoverPlantable;
			if (_visible && !_loggedShow)
			{
				_loggedShow = true;
				GD.Print(PlantPlacementMarkerEntry.LogPrefix + "首次显示（整行整列）：悬停格=(" +
				         hover.X + "," + hover.Y + ") 色带=" + cfg.BandWidth +
				         " 网格=" + mgr.gridNum.X + "x" + mgr.gridNum.Y);
			}
			Draw(cfg, mgr, mf.mapControl.mapNode, mf.config, delta);
			return;
		}

		// ---- 逐格标识 ----
		if (needRefresh)
		{
			_cellTimer = 0.0;
			RebuildCells(mgr, packetConfig);
		}

		_visible = _cells.Count > 0;
		if (_visible && !PlantPlacementMarkerEntry.FirstShowLogged)
		{
			PlantPlacementMarkerEntry.FirstShowLogged = true;
			GD.Print(PlantPlacementMarkerEntry.LogPrefix + "首次显示：样式=" + cfg.Style +
			         " 可种格=" + _cells.Count + " 网格=" + mgr.gridNum.X + "x" + mgr.gridNum.Y +
			         " 格尺寸=(" + mgr.gridSize.X + "," + mgr.gridSize.Y + ") 原点=(" +
			         mgr.gridBeginPos.X + "," + mgr.gridBeginPos.Y + ") 颜色=" + cfg.Tint.ToHtml() +
			         " 行过滤=" + (_linesGated ? "启用" : "跳过"));
		}
		Draw(cfg, mgr, mf.mapControl.mapNode, mf.config, delta);
	}

	/// <summary>
	/// 渲染链路冒烟测试：不依赖战斗场景，直接在屏幕中央画「圆环 + 十字」。
	/// 用途 —— 把「RenderingServer 能不能画」与「战斗/选卡逻辑对不对」彻底分开验证。
	/// </summary>
	private static void DrawSmoke(MarkerSettings cfg, double delta)
	{
		try
		{
			SceneTree tree = Engine.GetMainLoop() as SceneTree;
			if (tree == null || tree.Root == null)
			{
				Hide();
				return;
			}
			// 用一个**原生** Node2D 当画布父级（不写子类，避免引擎不回调的问题）
			if (!GodotObject.IsInstanceValid(_smokeHolder))
			{
				_smokeHolder = new Node2D { Name = "PlantPlacementMarkerSmoke" };
				tree.Root.AddChild(_smokeHolder);
				_rid = default;
			}
			if (!_rid.IsValid)
			{
				_rid = RenderingServer.CanvasItemCreate();
				RenderingServer.CanvasItemSetParent(_rid, _smokeHolder.GetCanvasItem());
				RenderingServer.CanvasItemSetZIndex(_rid, 4090);
				RenderingServer.CanvasItemSetZAsRelativeToParent(_rid, false);
			}
			_host = _smokeHolder;
			_smokeHolder.Position = tree.Root.GetVisibleRect().Size * 0.5f;

			RenderingServer.CanvasItemClear(_rid);
			RenderingServer.CanvasItemSetTransform(_rid, Transform2D.Identity);
			RenderingServer.CanvasItemSetVisible(_rid, true);

			Color tint = cfg.Tint;
			DrawRing(Vector2.Zero, 46f, tint, 3f);
			DrawCross(Vector2.Zero, 22f, tint, 3f);

			_visible = true;
			if (!_smokeLogged)
			{
				_smokeLogged = true;
				GD.Print(PlantPlacementMarkerEntry.LogPrefix + "冒烟测试：已在屏幕中央绘制（判断渲染链路是否可用）");
			}
			TickScreenshot(cfg, delta);
		}
		catch (Exception e)
		{
			if (!_smokeErrLogged)
			{
				_smokeErrLogged = true;
				try { GD.PushWarning(PlantPlacementMarkerEntry.LogPrefix + "冒烟测试异常：" + e); } catch { }
			}
		}
	}

	private static bool _smokeLogged;
	private static bool _smokeErrLogged;
	private static bool _curveLogged;
	private static bool _calibLogged;

	/// <summary>超级大地图：格子总数 &gt; 100（普通 9x6=54、大图 11x7=77 不算；27x15=405 算）。</summary>
	private static bool IsSuperBigMap(TowerDefenseManager mgr)
	{
		try
		{
			long n = (long)mgr.gridNum.X * mgr.gridNum.Y;
			return n > 100L || mgr.gridNum.X > 12 || mgr.gridNum.Y > 8;
		}
		catch { return false; }
	}

	private static bool IsBattleScene(TowerDefenseManager mgr)
	{
		try { return GodotObject.IsInstanceValid(mgr.currentControl); }
		catch { return false; }
	}

	// ------------------------------------------------------------------ RID
	private static bool EnsureRid(Node2D host)
	{
		try
		{
			if (!_rid.IsValid)
			{
				_rid = RenderingServer.CanvasItemCreate();
				RenderingServer.CanvasItemSetParent(_rid, host.GetCanvasItem());
				RenderingServer.CanvasItemSetZIndex(_rid, ZIndexValue);
				RenderingServer.CanvasItemSetZAsRelativeToParent(_rid, false);
				RenderingServer.CanvasItemSetVisible(_rid, true);
			}
			else if (!ReferenceEquals(_host, host))
			{
				RenderingServer.CanvasItemSetParent(_rid, host.GetCanvasItem());
			}
			_host = host;
			return true;
		}
		catch (Exception e)
		{
			if (!_errorLogged)
			{
				_errorLogged = true;
				try { GD.PushWarning(PlantPlacementMarkerEntry.LogPrefix + "创建绘制画布失败：" + e.Message); } catch { }
			}
			return false;
		}
	}

	public static void Destroy()
	{
		try
		{
			if (_rid.IsValid) { RenderingServer.FreeRid(_rid); }
		}
		catch { }
		_rid = default;
		_host = null;
	}

	private static void Hide()
	{
		_visible = false;
		if (_rid.IsValid)
		{
			try
			{
				RenderingServer.CanvasItemClear(_rid);
				RenderingServer.CanvasItemSetVisible(_rid, false);
			}
			catch { }
		}
	}

	// ------------------------------------------------------------------ 数据
	private static void RebuildAllCells(TowerDefenseManager mgr)
	{
		_cells.Clear();
		for (int y = 1; y <= mgr.gridNum.Y; y++)
		{
			for (int x = 1; x <= mgr.gridNum.X; x++)
			{
				_cells.Add(new Vector2I(x, y));
			}
		}
	}

	private static void RebuildCells(TowerDefenseManager mgr, TowerDefensePacketConfig packetConfig)
	{
		_cells.Clear();
		int nx = mgr.gridNum.X;
		int ny = mgr.gridNum.Y;

		// lineUse 为空时 GetMapLineUse() 恒 false ⇒ 无脑用会把整片草坪判掉
		Godot.Collections.Array<bool> lineArr = null;
		try { lineArr = mgr.GetMapLineUseArr(); } catch { }
		bool canJudgeLines = lineArr != null && lineArr.Count > ny;
		_linesGated = canJudgeLines;

		for (int y = 1; y <= ny; y++)
		{
			bool lineOk = true;
			if (canJudgeLines) { try { lineOk = mgr.GetMapLineUse(y); } catch { lineOk = true; } }
			if (!lineOk) { continue; }
			for (int x = 1; x <= nx; x++)
			{
				Vector2I gp = new Vector2I(x, y);
				TowerDefenseCellInstance cell = TowerDefenseManager.GetMapCell(gp);
				if (!GodotObject.IsInstanceValid(cell)) { continue; }
				bool ok;
				try { ok = cell.CanPacketPlant(packetConfig); }
				catch { ok = false; }
				if (ok) { _cells.Add(gp); }
			}
		}
	}

	private static Vector2 CellTopLeft(TowerDefenseManager mgr, Vector2I gridPos)
	{
		return new Vector2(
			mgr.gridBeginPos.X + (gridPos.X - 1) * mgr.gridSize.X,
			mgr.gridBeginPos.Y + (gridPos.Y - 1) * mgr.gridSize.Y);
	}

	/// <summary>
	/// 标识锚点 = 格子中心，但要**减去该格的 groundHeightCurve 偏移**。
	/// 依据（游戏自己的取格公式，TowerDefenseManager.GetMapGridPosFromMouse）：
	///     rowTop    = gridBeginPos.Y + i*gridSize.Y - curve.Sample(t)
	///     rowBottom = gridBeginPos.Y + (i+1)*gridSize.Y - curve.Sample(t)
	/// ⇒ 每行的"可见带到哪"，由曲线决定；忽略它就会整体偏上（本机 Backyard 实测）。
	/// </summary>
	private static Vector2 CellAnchor(TowerDefenseManager mgr, TowerDefenseMapConfig mapCfg, Vector2I gridPos, MarkerSettings cfg)
	{
		// 美术行高校准表（按贴图文件名匹配）：originDelta = 美术顶边相对 gridBeginPos.Y 的偏移，
		// pitchScale = 美术行距 / gridSize.Y。没命中的图用 1.0/0（= 纯 gridSize），再由玩家微调。
		// 实测结论（Backyard 夜，玩家截图逐行反推）：美术行距就是均匀的 gridSize.Y，
		// 偏差是一个**常数**（行中心比格子几何中心低约 16 世界像素）⇒ 用 offsetY 补，不用改行距。
		// RowPitchScale 仍保留给"确实非均匀行高"的自制图自行校正。
		float originDelta = 0f;
		float scale = (cfg.RowPitchScale > 0.5f && cfg.RowPitchScale < 2f) ? cfg.RowPitchScale : 1f;

		float ax = mgr.gridBeginPos.X + (gridPos.X - 0.5f) * mgr.gridSize.X;
		float ay = mgr.gridBeginPos.Y + originDelta + (gridPos.Y - 0.5f) * mgr.gridSize.Y * scale;

		try
		{
			TowerDefenseCellInstance cell = TowerDefenseManager.GetMapCell(gridPos);
			if (GodotObject.IsInstanceValid(cell) && GodotObject.IsInstanceValid(cell.groundHeightCurve))
			{
				Curve curve = cell.groundHeightCurve.Curve;
				if (curve != null)
				{
					ay -= (int)curve.Sample(0.5f);
				}
			}
		}
		catch { }

		if (!_calibLogged)
		{
			_calibLogged = true;
			GD.Print(PlantPlacementMarkerEntry.LogPrefix + "定位校准：originDelta=" + originDelta +
			         " pitchScale=" + scale.ToString("0.###") + "（贴图=" + (mapCfg?.mapTexturePath ?? "?") + "）");
		}

		return new Vector2(ax + cfg.OffsetX, ay + cfg.OffsetY);
	}

	private static Vector2 GetMouseWorld(TowerDefenseMapControl mapControl)
	{
		try
		{
			Viewport vp = mapControl.GetViewport();
			if (vp == null) { return Vector2.Zero; }
			return mapControl.GetCanvasTransform().AffineInverse() * vp.GetMousePosition();
		}
		catch { return Vector2.Zero; }
	}

	// ------------------------------------------------------------------ 绘制
	private static void Draw(MarkerSettings cfg, TowerDefenseManager mgr, Node2D artNode, TowerDefenseMapConfig mapCfg, double delta)
	{
		if (!_rid.IsValid || !GodotObject.IsInstanceValid(_host))
		{
			Hide();
			return;
		}

		try
		{
			RenderingServer.CanvasItemClear(_rid);
			if (!_visible)
			{
				RenderingServer.CanvasItemSetVisible(_rid, false);
				return;
			}
			RenderingServer.CanvasItemSetVisible(_rid, true);
			// 格子坐标（gridBeginPos/gridSize）是**地图美术**的像素坐标系（已用真实贴图核对过）。
			// 所以局部变换 = spriteNode⁻¹ · mapNode：既落在地图美术坐标系上，又留在上层 CanvasLayer 里（压过植物）。
			Transform2D xf = _host.GlobalTransform.AffineInverse();
			if (GodotObject.IsInstanceValid(artNode))
			{
				xf = xf * artNode.GlobalTransform;
			}
			RenderingServer.CanvasItemSetTransform(_rid, xf);

			Vector2 cellSize = new Vector2(mgr.gridSize.X, mgr.gridSize.Y);
			if (cellSize.X <= 0f || cellSize.Y <= 0f) { return; }

			float scale = (cfg.Scale > 0.1f && cfg.Scale < 4f) ? cfg.Scale : 1f;
			float unit = Mathf.Min(cellSize.X, cellSize.Y) * scale;
			float p = (float)((1.0 - Math.Cos(2.0 * Math.PI * _pulse / PulsePeriod)) * 0.5);
			Color tint = cfg.Tint;
			float stroke = cfg.StrokeWidth;

			switch (cfg.Style)
			{
				case MarkerStyle.RowColumn:
					DrawRowColumn(cfg, mgr, mapCfg, cellSize, unit, tint, stroke);
					break;

				case MarkerStyle.CornersCross:
					for (int i = 0; i < _cells.Count; i++)
					{
						Vector2 anchor = CellAnchor(mgr, mapCfg, _cells[i], cfg);
						DrawCorners(anchor - cellSize * 0.5f, cellSize, unit, p, tint, stroke);
						if (cfg.ShowCross) { DrawCross(anchor, unit * 0.119f, tint, stroke); }
					}
					break;

				default:
					for (int i = 0; i < _cells.Count; i++)
					{
						Vector2 c = CellAnchor(mgr, mapCfg, _cells[i], cfg);
						float r = unit * (0.17f + 0.11f * p);
						DrawRing(c, r, tint, stroke);
						if (cfg.ShowCross) { DrawCross(c, unit * 0.119f, tint, stroke); }
					}
					break;
			}

			// 诊断：把 1..gridNum 的格子边框也画出来（截图后可直接读偏移量）
			if (cfg.DebugShowGrid)
			{
				Color edge = new Color(tint.R, tint.G, tint.B, 0.45f);
				for (int y = 1; y <= mgr.gridNum.Y; y++)
				{
					for (int x = 1; x <= mgr.gridNum.X; x++)
					{
						Vector2 tl = CellTopLeft(mgr, new Vector2I(x, y));
						Vector2 tr = new Vector2(tl.X + cellSize.X, tl.Y);
						Vector2 bl = new Vector2(tl.X, tl.Y + cellSize.Y);
						Vector2 br = new Vector2(tl.X + cellSize.X, tl.Y + cellSize.Y);
						RenderingServer.CanvasItemAddLine(_rid, tl, tr, edge, 1f, true);
						RenderingServer.CanvasItemAddLine(_rid, tr, br, edge, 1f, true);
						RenderingServer.CanvasItemAddLine(_rid, bl, br, edge, 1f, true);
						RenderingServer.CanvasItemAddLine(_rid, tl, bl, edge, 1f, true);
					}
				}
			}

			TickScreenshot(cfg, delta);
		}
		catch (Exception e)
		{
			if (!_errorLogged)
			{
				_errorLogged = true;
				try { GD.PushWarning(PlantPlacementMarkerEntry.LogPrefix + "绘制异常（已捕获）：" + e); } catch { }
			}
		}
	}

	internal static Vector2[] BuildRingPoints(Vector2 center, float radius, int steps)
	{
		Vector2[] pts = new Vector2[steps + 1];
		for (int i = 0; i <= steps; i++)
		{
			double ang = 2.0 * Math.PI * i / steps;
			pts[i] = new Vector2(center.X + (float)Math.Cos(ang) * radius,
			                     center.Y + (float)Math.Sin(ang) * radius);
		}
		return pts;
	}

	/// <summary>圆环：用闭合折线画（CanvasItemAddCircle 的重载在各版本不一致，折线最稳）。</summary>
	private static void DrawRing(Vector2 center, float radius, Color tint, float stroke, int steps = 40)
	{
		Vector2[] pts = BuildRingPoints(center, radius, steps);
		Color[] cols = new Color[pts.Length];
		for (int i = 0; i < pts.Length; i++) { cols[i] = tint; }
		RenderingServer.CanvasItemAddPolyline(_rid, pts, cols, stroke, true);
	}

	private static void DrawCross(Vector2 c, float half, Color tint, float stroke)
	{
		RenderingServer.CanvasItemAddLine(_rid, new Vector2(c.X - half, c.Y), new Vector2(c.X + half, c.Y), tint, stroke, true);
		RenderingServer.CanvasItemAddLine(_rid, new Vector2(c.X, c.Y - half), new Vector2(c.X, c.Y + half), tint, stroke, true);
	}

	/// <summary>四角几何：返回 4 组折线（每组 = 圆角采样 + 横臂末端）；竖臂由调用方单独画。</summary>
	internal static void BuildCorners(Vector2 tl, Vector2 cellSize, float unit, float p,
	                                 List<Vector2[]> lines, List<Vector2[]> stems)
	{
		float padX = cellSize.X * 0.158f;
		float padY = cellSize.Y * 0.158f;
		float armX = cellSize.X * 0.14f;
		float armY = cellSize.Y * 0.14f;
		float rad = unit * 0.07f;
		float d = unit * 0.08f * p;
		const int Steps = 10;

		for (int i = 0; i < 4; i++)
		{
			float sx = (i == 0 || i == 2) ? 1f : -1f;      // 0左上 1右上 2左下 3右下
			float sy = (i < 2) ? 1f : -1f;
			Vector2 basePt = new Vector2(
				(i == 0 || i == 2) ? tl.X + padX : tl.X + cellSize.X - padX,
				(i < 2) ? tl.Y + padY : tl.Y + cellSize.Y - padY);
			Vector2 c0 = basePt + new Vector2(sx * d, sy * d);

			Vector2 vArm = new Vector2(c0.X, c0.Y + sy * armY);
			Vector2 arcA = new Vector2(c0.X, c0.Y + sy * rad);
			Vector2 hArm = new Vector2(c0.X + sx * armX, c0.Y);
			Vector2 arcCenter = new Vector2(c0.X + sx * rad, c0.Y + sy * rad);

			double a0;
			switch (i)
			{
				case 0: a0 = Math.PI; break;
				case 1: a0 = Math.PI * 1.5; break;
				case 2: a0 = Math.PI * 0.5; break;
				default: a0 = 0.0; break;
			}

			// 容量 = arcA(1) + 圆角采样(Steps+1) + hArm(1)
			Vector2[] pts = new Vector2[Steps + 3];
			int n = 0;
			pts[n++] = arcA;
			for (int k = 0; k <= Steps; k++)
			{
				double ang = a0 + (Math.PI * 0.5) * (k / (double)Steps);
				pts[n++] = new Vector2(arcCenter.X + (float)Math.Cos(ang) * rad,
					arcCenter.Y + (float)Math.Sin(ang) * rad);
			}
			pts[n++] = hArm;
			Array.Resize(ref pts, n);
			lines.Add(pts);
			stems.Add(new Vector2[] { vArm, arcA });
		}
	}

	private static void DrawCorners(Vector2 tl, Vector2 cellSize, float unit, float p, Color tint, float stroke)
	{
		List<Vector2[]> lines = new List<Vector2[]>(4);
		List<Vector2[]> stems = new List<Vector2[]>(4);
		BuildCorners(tl, cellSize, unit, p, lines, stems);
		for (int i = 0; i < lines.Count; i++)
		{
			Vector2[] stem = stems[i];
			RenderingServer.CanvasItemAddLine(_rid, stem[0], stem[1], tint, stroke, true);
			Vector2[] pts = lines[i];
			Color[] cols = new Color[pts.Length];
			for (int k = 0; k < pts.Length; k++) { cols[k] = tint; }
			RenderingServer.CanvasItemAddPolyline(_rid, pts, cols, stroke, true);
		}
	}

	private static void DrawRowColumn(MarkerSettings cfg, TowerDefenseManager mgr, TowerDefenseMapConfig mapCfg, Vector2 cellSize,
	                                  float unit, Color tint, float stroke)
	{
		if (!_haveHover || !_hoverPlantable) { return; }

		Vector2 center = CellAnchor(mgr, mapCfg, _hover, cfg);
		// 整行整列：**不做缩放动画**（用户要求），色带宽度恒等于「线条粗细」档位对应的世界像素值。
		// 注意：p（脉动相位）在这个样式里不再参与任何尺寸计算。
		float band = cfg.BandWidth;

		float left = mgr.gridBeginPos.X;
		float top = mgr.gridBeginPos.Y;
		float right = left + mgr.gridNum.X * mgr.gridSize.X;
		float bottom = top + mgr.gridNum.Y * mgr.gridSize.Y;

		Color fill = new Color(tint.R, tint.G, tint.B, 0.22f);
		Color edge = new Color(tint.R, tint.G, tint.B, Mathf.Clamp(tint.A * 0.85f, 0f, 1f));

		Rect2 rowRect = new Rect2(left, center.Y - band * 0.5f, right - left, band);
		RenderingServer.CanvasItemAddRect(_rid, rowRect, fill, true);
		RenderingServer.CanvasItemAddLine(_rid, new Vector2(left, rowRect.Position.Y), new Vector2(right, rowRect.Position.Y), edge, stroke * 0.7f, true);
		RenderingServer.CanvasItemAddLine(_rid, new Vector2(left, rowRect.End.Y), new Vector2(right, rowRect.End.Y), edge, stroke * 0.7f, true);

		Rect2 colRect = new Rect2(center.X - band * 0.5f, top, band, bottom - top);
		RenderingServer.CanvasItemAddRect(_rid, colRect, fill, true);
		RenderingServer.CanvasItemAddLine(_rid, new Vector2(colRect.Position.X, top), new Vector2(colRect.Position.X, bottom), edge, stroke * 0.7f, true);
		RenderingServer.CanvasItemAddLine(_rid, new Vector2(colRect.End.X, top), new Vector2(colRect.End.X, bottom), edge, stroke * 0.7f, true);

		if (cfg.ShowCross)
		{
			DrawCross(center, unit * 0.42f, tint, stroke * 1.6f);
		}
	}

	// ------------------------------------------------------------------ 截图诊断
	private static void TickScreenshot(MarkerSettings cfg, double delta)
	{
		// 开了「输出诊断日志」也顺带截一张（方便事后取证/量偏移，不用玩家额外操作）
		if ((!cfg.DebugScreenshot && !PlantPlacementMarkerEntry.EnableLog) || !_visible)
		{
			_visibleTime = 0.0;
			_shotDone = false;
			return;
		}
		_visibleTime += delta;
		if (_shotDone || _visibleTime < 1.2) { return; }
		_shotDone = true;
		try
		{
			RenderingServer.ForceDraw();
			Viewport vp = _host?.GetViewport();
			Image img = vp?.GetTexture()?.GetImage();
			if (img == null)
			{
				GD.Print(PlantPlacementMarkerEntry.LogPrefix + "截图失败：视口纹理为空");
				return;
			}
			string rel = "user://PlantPlacementMarker_shot.png";
			Error err = img.SavePng(rel);
			GD.Print(PlantPlacementMarkerEntry.LogPrefix + "截图已保存：" +
			         ProjectSettings.GlobalizePath(rel) + "（err=" + err + "，" +
			         img.GetWidth() + "x" + img.GetHeight() + "）");
		}
		catch (Exception e)
		{
			GD.Print(PlantPlacementMarkerEntry.LogPrefix + "截图异常：" + e.Message);
		}
	}
}
