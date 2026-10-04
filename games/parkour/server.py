# -*- coding: utf-8 -*-
"""极速跑酷（parkour）服务端：大厅房间管理、实时榜单广播、成绩入库。"""

from datetime import datetime

from flask import jsonify, request

from db import execute, query
from games.base import BaseGame
from logger import get_ip, log_game_score

# 所有跑酷玩家共用一个房间号，前端不需要知道具体值
ROOM_ID = "parkour_lobby"

# 实时榜最多显示多少人
MAX_LIVE = 8

# 单局分数上限，防止前端乱传超大数字
MAX_SCORE = 1000000

# sid -> {"name": 昵称, "score": 本局分数, "coins": 金币, "alive": 是否在跑, "best": 历史最高}
PLAYERS = {}

# 成绩表是否已确认存在，避免每次提交都重复执行建表语句
_TABLE_READY = False


# 首次使用时确保成绩表存在，防止全新部署时写入报错
def _ensure_table():
    global _TABLE_READY
    if _TABLE_READY:
        return
    try:
        execute(
            "CREATE TABLE IF NOT EXISTS game_scores("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "game_key TEXT NOT NULL,"
            "student_name TEXT NOT NULL,"
            "score INTEGER NOT NULL DEFAULT 0,"
            "detail TEXT,"
            "created_at TEXT)"
        )
        _TABLE_READY = True
    except Exception as exc:
        print(f"[跑酷] 建表检查失败: {exc}")


# 把前端传来的数字安全转换成指定区间内的整数
def _clamp_int(value, low, high):
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        num = low
    if num < low:
        num = low
    if num > high:
        num = high
    return num


# 清洗玩家昵称：去掉换行与首尾空格，最长 16 个字符
def _clean_name(value):
    name = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    name = name[:16]
    if not name:
        name = "同学"
    return name


# 组装按分数从高到低排序的实时榜单
def _live_list():
    items = []
    for info in PLAYERS.values():
        items.append({
            "name": info["name"],
            "score": info["score"],
            "coins": info["coins"],
            "alive": info["alive"],
        })
    items.sort(key=lambda item: item["score"], reverse=True)
    return items[:MAX_LIVE]


# 组装广播给整个房间的状态数据
def _room_state():
    return {"count": len(PLAYERS), "live": _live_list()}


# 向跑酷房间广播一个事件
def _broadcast(socketio, namespace, event, payload):
    socketio.emit(event, payload, namespace=namespace, room=ROOM_ID)


# 把一局成绩写入数据库并打印彩色控制台日志
def _save_score(game_key, name, score, detail):
    _ensure_table()
    execute(
        "INSERT INTO game_scores(game_key, student_name, score, detail, created_at) "
        "VALUES(?,?,?,?,?)",
        (game_key, name, score, detail, datetime.now().isoformat(timespec="seconds")),
    )
    ip = None
    try:
        ip = get_ip()
    except Exception:
        ip = None
    log_game_score(game_key, name, score, ip=ip)


class Game(BaseGame):

    # 注册 REST 路由，最终路径为 /api/game/parkour/xxx
    def register_routes(self, bp):

        @bp.route("/ping")
        def ping():
            """健康检查：确认插件已加载，并返回当前在线人数。"""
            return jsonify(ok=True, game=self.key, online=len(PLAYERS))

        @bp.route("/leaderboard")
        def leaderboard():
            """返回历史最高分榜（同一学生只保留最高分）。"""
            _ensure_table()
            limit = _clamp_int(request.args.get("limit", 10), 1, 50)
            rows = []
            try:
                rows = query(
                    "SELECT student_name, MAX(score) AS best, MAX(created_at) AS last_time "
                    "FROM game_scores WHERE game_key=? GROUP BY student_name "
                    "ORDER BY best DESC LIMIT ?",
                    (self.key, limit),
                )
            except Exception as exc:
                print(f"[跑酷] 读取历史榜失败: {exc}")
            board = []
            for row in rows:
                board.append({
                    "name": row["student_name"],
                    "score": int(row["best"] or 0),
                    "time": row["last_time"] or "",
                })
            return jsonify(ok=True, leaderboard=board)

        @bp.route("/score", methods=["POST"])
        def submit_score():
            """REST 备用提交入口：Socket.IO 掉线时前端改走这里交成绩。"""
            data = request.get_json(silent=True) or {}
            name = _clean_name(data.get("name"))
            score = _clamp_int(data.get("score"), 0, MAX_SCORE)
            distance = _clamp_int(data.get("distance"), 0, MAX_SCORE)
            coins = _clamp_int(data.get("coins"), 0, MAX_SCORE)
            detail = f"距离 {distance} 米，金币 {coins} 枚"
            try:
                _save_score(self.key, name, score, detail)
            except Exception as exc:
                print(f"[跑酷] 成绩写入失败: {exc}")
                return jsonify(ok=False, msg="成绩写入失败"), 500
            return jsonify(ok=True, name=name, score=score)
    # 注册 SocketIO 事件，namespace 为 /game/parkour
    def register_socketio(self, socketio, namespace):

        @socketio.on("join", namespace=namespace)
        def on_join(data=None):
            """玩家进入跑酷大厅：记录身份、进房、回传个人最高分并广播房间状态。"""
            data = data or {}
            sid = request.sid
            name = _clean_name(data.get("name"))
            best = 0
            try:
                row = query(
                    "SELECT MAX(score) AS best FROM game_scores "
                    "WHERE game_key=? AND student_name=?",
                    (self.key, name),
                    one=True,
                )
                if row is not None and row["best"] is not None:
                    best = int(row["best"])
            except Exception as exc:
                print(f"[跑酷] 读取个人最高分失败: {exc}")
            PLAYERS[sid] = {
                "name": name,
                "score": 0,
                "coins": 0,
                "alive": False,
                "best": best,
            }
            socketio.server.enter_room(sid, ROOM_ID, namespace=namespace)
            socketio.emit(
                "joined",
                {"sid": sid, "name": name, "best": best, "online": len(PLAYERS)},
                namespace=namespace,
                room=sid,
            )
            _broadcast(socketio, namespace, "room_update", _room_state())

        @socketio.on("progress", namespace=namespace)
        def on_progress(data=None):
            """收到玩家实时进度：刷新实时榜并广播给同房间所有人。"""
            info = PLAYERS.get(request.sid)
            if info is None:
                return
            data = data or {}
            info["score"] = _clamp_int(data.get("score"), 0, MAX_SCORE)
            info["coins"] = _clamp_int(data.get("coins"), 0, MAX_SCORE)
            info["alive"] = True
            _broadcast(socketio, namespace, "room_update", _room_state())

        @socketio.on("dead", namespace=namespace)
        def on_dead(data=None):
            """收到玩家本局结束的通知：标记为不在奔跑并广播实时榜。"""
            info = PLAYERS.get(request.sid)
            if info is None:
                return
            data = data or {}
            info["score"] = _clamp_int(data.get("score"), 0, MAX_SCORE)
            info["coins"] = _clamp_int(data.get("coins"), 0, MAX_SCORE)
            info["alive"] = False
            _broadcast(socketio, namespace, "room_update", _room_state())

        @socketio.on("submit", namespace=namespace)
        def on_submit(data=None):
            """提交成绩：校验后写入数据库，广播战报，并把结果回执给提交者。"""
            data = data or {}
            info = PLAYERS.get(request.sid)
            fallback_name = info["name"] if info else "同学"
            name = _clean_name(data.get("name") or fallback_name)
            score = _clamp_int(data.get("score"), 0, MAX_SCORE)
            distance = _clamp_int(data.get("distance"), 0, MAX_SCORE)
            coins = _clamp_int(data.get("coins"), 0, MAX_SCORE)
            detail = f"距离 {distance} 米，金币 {coins} 枚"
            try:
                _save_score(self.key, name, score, detail)
            except Exception as exc:
                print(f"[跑酷] 成绩写入失败: {exc}")
                return {"ok": False, "msg": "成绩写入失败"}
            is_best = False
            best = score
            if info is not None:
                if score > info.get("best", 0):
                    info["best"] = score
                    is_best = True
                info["name"] = name
                info["score"] = score
                info["coins"] = coins
                info["alive"] = False
                best = info["best"]
            _broadcast(socketio, namespace, "score_feed", {
                "name": name,
                "score": score,
                "coins": coins,
                "best": is_best,
            })
            _broadcast(socketio, namespace, "room_update", _room_state())
            return {"ok": True, "name": name, "score": score, "best": best, "is_best": is_best}

        @socketio.on("disconnect", namespace=namespace)
        def on_disconnect():
            """玩家断开连接：从大厅移除并广播最新在线榜。"""
            if PLAYERS.pop(request.sid, None) is not None:
                _broadcast(socketio, namespace, "room_update", _room_state())