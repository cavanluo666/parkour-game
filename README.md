# 极速跑酷（parkour）

一个 2D 横版无限跑酷小游戏：自动向右奔跑、跳跃与滑铲躲避障碍、吃金币，
带**全局实时榜**与历史最高分榜。前端是单文件页面（自带 CSS/JS，无需构建），
后端用 Flask + Flask-SocketIO 提供大厅与成绩接口。

> **这是一个「游戏插件」，不是独立应用。** 它按约定挂在一个宿主 Web 系统上，
> 依赖宿主提供的数据库、日志与游戏加载框架。仓库里的
> [`docs/宿主接口.md`](docs/宿主接口.md) 完整描述了这套约定；
> 宿主接口很薄（3 个模块、6 个函数），照着实现即可跑起来。

## 一、玩法

角色自动向右奔跑，速度越来越快。**地面方块要跳过去，悬挂横管要滑铲钻过去**，路上金币跳起来吃。
撞一次掉一条命（3 条命，受伤后 1.4 秒无敌闪烁），命掉光本局结束。

- 分数 = 距离（米）+ 金币 × 10
- 跳跃：空格 / ↑ / W / 点击画面上半屏（空中可再跳一次）
- 滑铲：↓ / S / 按住画面下半屏
- 暂停：P（切到别的标签页会自动暂停）；重开：R

## 二、目录结构

```
跑酷游戏/
├─ README.md
├─ LICENSE
├─ docs/
│  └─ 宿主接口.md        # 宿主需要提供的模块与函数契约
└─ games/
   └─ parkour/
      ├─ game.json      # 元数据（key=parkour，最多 20 人）
      ├─ server.py      # SocketIO 大厅 + REST 成绩接口
      └─ static/
         └─ index.html  # 完整独立页面（自带 CSS/JS，无需构建）
```

## 三、部署步骤

1. 把整个 `parkour` 目录放进宿主项目的 `games/` 下（与 `base.py`、`loader.py` 同级）。
2. 按 [`docs/宿主接口.md`](docs/宿主接口.md) 确认宿主已提供 `db`、`logger`、`games.base` 三个模块。
3. 重启 Flask 进程（loader 只在启动时扫描游戏目录）：
   - 直接运行：Ctrl+C 停掉后重新 `python app.py`
   - 后台 / systemd：`systemctl restart <你的服务名>`
   - 调试模式：Flask 热重载会自己重新加载，但在线状态会清空，属正常
4. 浏览器打开 `/game`，列表里出现「🏃 极速跑酷」即加载成功；点进去由 `/game/parkour` 用 iframe 承载。
5. 确认数据库已就绪：首次提交成绩时 `server.py` 会自动执行
   `CREATE TABLE IF NOT EXISTS game_scores(...)`，不需要手工建表。
6. 上线前自检：访问 `/api/game/parkour/ping` 应返回 `{"ok": true, "game": "parkour", "online": 0}`。

## 四、接口清单

| 类型 | 地址 | 说明 |
| --- | --- | --- |
| REST | `GET  /api/game/parkour/ping` | 健康检查，返回在线人数 |
| REST | `GET  /api/game/parkour/leaderboard?limit=10` | 历史最高分榜（同一昵称取最高分） |
| REST | `POST /api/game/parkour/score` | 备用提交入口（Socket 掉线时前端走这里） |
| Socket | `join` / `progress` / `dead` / `submit` / `disconnect` | 命名空间 `/game/parkour` |
| Socket | 服务端推送 `joined` / `room_update` / `score_feed` | 大厅状态与战报 |

所有提交的分数都会走 `_clamp_int` 夹紧到 `0 ~ 1000000`，昵称清洗到 16 字符以内。

## 五、测试要点

1. **加载**：访问 `/game/parkour`，页面顶部状态显示「已连接大厅」，右侧实时榜出现「等待同学加入…」。
2. **可玩性**：按空格开始，方块必须跳、悬挂横管必须滑铲；撞 3 次后弹出结算面板，分数应等于「距离 + 金币 × 10」。
3. **联机**：两台设备同时打开，一台在跑时，另一台右侧「本局实时榜」能看到对方分数后面有绿点（表示正在奔跑）；结束后消失。
4. **成绩入库**：点提交成绩后弹出「成绩已提交」提示，控制台出现彩色 `log_game_score` 日志；
   `SELECT * FROM game_scores WHERE game_key='parkour' ORDER BY id DESC LIMIT 5;` 能看到记录。
5. **主题兼容**：在宿主提供的皮肤间切换，游戏画面（含 Canvas 内绘制）1.5 秒内跟随变色，深色 / 赛博主题下文字与障碍仍清晰可见。
6. **移动端**：手机打开，点上半屏能跳、按住下半屏能滑铲；窗口宽度小于 760px 时侧栏自动折到画面下方。

## 六、手感调参（static/index.html 顶部常量）

| 常量 | 默认 | 作用 |
| --- | --- | --- |
| `BASE_SPEED` / `MAX_SPEED` | 380 / 780 | 初速度与速度上限 |
| `JUMP_SPEED` / `JUMP_SPEED2` | 760 / 640 | 一段跳、二段跳初速度 |
| `SLIDE_TIME` | 0.55 | 滑铲持续秒数 |
| `MAX_LIVES` | 3 | 初始生命 |
| `COIN_SCORE` | 10 | 每枚金币折算分数 |
| `PX_PER_METER` | 8 | 8 像素算 1 米 |

难度曲线在 `updateGame()` 里：`420 / state.speed` 控制障碍间隔，速度越快间隔时间越短、像素间距保持不变。

## 七、隐私说明

游戏会把玩家提交的**显示名称**与成绩一起写入 `game_scores` 表，用于排行榜。
若你在真实教室 / 组织环境中部署，请注意：

- 前端会尝试从宿主页面的欢迎语或 `localStorage` 中自动读取姓名
  （键名依次为 `parkour_name`、`student_name`、`studentName`、`student`、`name`、`username`）。
  如果你不希望采集真名，请让玩家手动输入昵称，或在宿主侧移除这些元素与键。
- 名称会被清洗为最长 16 字符，仅用于展示，但仍属于个人信息，
  请按你所在地区的规定处理留存与删除需求。

## 八、许可证

本项目以 **GNU General Public License v3.0 or later** 发布，完整条款见 [`LICENSE`](LICENSE)。

```
Copyright (C) 2026 LCH
```

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.
