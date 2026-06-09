# AI 指挥调度中心 — 障碍/地形 Demo 场景 & 自然语言位置控制

> 分支 feature/multi-geo，2026-06-08。设计/计划见
> docs/superpowers/specs/2026-06-08-fleet-command-center-positions-and-arena-design.md
> docs/superpowers/plans/2026-06-08-fleet-command-center-positions-and-arena.md

## 启动

完整体验（codex 大脑 + 3D 窗口 + 网页控制台 + demo 场景）：

```bash
conda run -n agi python -m g1_brain.fleet.sim.command_center --viewer --scene demo
# 浏览器会自动打开 http://127.0.0.1:8787/
```

不依赖 codex（确定性，离线也能做位置控制）：加 `--no-codex`。
单机测试：加 `--solo`（只有 g1_a）。回到空地板：`--scene bare`。

## 自然语言位置控制（无需 codex 也可用）

在网页 "AI 指挥官" 输入框里直接说：

- 绝对坐标：`g1_a 走到 2,1` / `g1_a go to 2,1`
- 命名地标：`去红色柱子` / `到集合点` / `左上角`
- 相对移动：`g1_a 前进 2米` / `g1_a 后退 1m`
- 多机：`两机都去集合点` / `all go to center`
- 编队动作仍然有效：`顺时针绕圈` / `面对面` / `抬双手`

地图上会画出所有障碍物和地标名字，方便你按名字下指令。

## 场景内容（轻量，性能友好）

- 走绕障碍（机器人自动绕行）：红/绿柱子、蓝/黄箱子、路障；矮墙是背景。
- 缓地形测试带（沿 +X，机器人走上去）：~10° 斜坡 + 低起伏 + 矮台阶。
- 全部是静态 box/cylinder 基本体（无 body/关节 → 0 自由度增加，无高度场/网格/
  额外光源），对 WSL2 软件渲染几乎零额外开销。

## 避障 vs 会合

导航默认绕开静态障碍；会合 / 面对面（await_barrier / face）时自动关闭"机器人
互相躲避"，所以两机仍能贴到一起。
