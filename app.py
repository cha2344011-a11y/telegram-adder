import os
import asyncio
import threading
import json
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO

from core.engine import scrape_members, InviteEngine, SCRAPED_FILE, INVITED_FILE, FAILED_FILE, PROGRESS_FILE
from core.scheduler import (DailyStateManager, load_all_accounts,
                             get_available_accounts, get_accounts_dashboard_data,
                             DailyAutoRunner)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "tg_migration_2024")
async_mode = "threading"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

invite_engine_instance = None
auto_runner_instance   = None  # DailyAutoRunner (background scheduler)

# Config file to persist target group
CONFIG_FILE = "data/app_config.json"
os.makedirs("data", exist_ok=True)

def load_app_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"target_group": "", "delay_min": 30, "delay_max": 60}

def save_app_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    env_accounts = load_all_accounts()
    config       = load_app_config()
    return render_template("index.html",
                           env_accounts_count=len(env_accounts),
                           is_cloud=bool(os.environ.get("API_ID_1")),
                           target_group=config.get("target_group", ""),
                           auto_running=bool(auto_runner_instance))


@app.route("/api/progress")
def get_progress():
    data = {"invited": 0, "failed": 0, "remaining": 0, "total": 0}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            data = json.load(f)
    accounts_data, daily_summary = get_accounts_dashboard_data()
    data["accounts"] = accounts_data
    data["daily"]    = daily_summary
    return jsonify(data)


@app.route("/api/accounts")
def get_accounts():
    accounts_data, daily_summary = get_accounts_dashboard_data()
    return jsonify({"accounts": accounts_data, "daily": daily_summary})


@app.route("/api/schedule")
def get_schedule():
    from core.scheduler import load_today_schedule
    schedule = load_today_schedule()
    # Return a simplified view per account
    result = {}
    for phone, data in schedule.items():
        acc = data.get("account", {})
        result[phone] = {
            "name":    acc.get("name", phone),
            "batches": data.get("batches", [])
        }
    return jsonify(result)


@app.route("/api/download/<file_type>")
def download_file(file_type):
    files = {"scraped": SCRAPED_FILE, "invited": INVITED_FILE, "failed": FAILED_FILE}
    path = files.get(file_type)
    if path and os.path.exists(path):
        return send_file(path, as_attachment=True)
    return jsonify({"error": "File not found"}), 404


@app.route("/api/otp", methods=["POST"])
def submit_otp():
    data = request.json
    with open(f"otp_{data['phone']}.tmp", "w") as f:
        f.write(data["code"])
    return jsonify({"status": "ok"})


@app.route("/api/config", methods=["GET", "POST"])
def app_config():
    if request.method == "POST":
        cfg = request.json
        save_app_config(cfg)
        return jsonify({"status": "ok"})
    return jsonify(load_app_config())


@app.route("/api/set-account-limit", methods=["POST"])
def set_account_limit():
    data  = request.json
    phone = data.get("phone")
    limit = int(data.get("limit", 120))
    config_file = "sessions_config.json"
    if os.path.exists(config_file):
        with open(config_file) as f:
            config = json.load(f)
        for acc in config["accounts"]:
            if acc["phone"] == phone:
                acc["daily_limit"] = limit
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        return jsonify({"status": "ok", "phone": phone, "limit": limit})
    return jsonify({"error": "sessions_config.json not found"}), 404


# ─────────────────────────────────────────────────────────────────────────────
#  SocketIO Events
# ─────────────────────────────────────────────────────────────────────────────

@socketio.on("start_scrape")
def handle_scrape(data):
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(scrape_members(
            int(data["api_id"]), data["api_hash"], data["phone"],
            data["source_group"], socketio, data.get("session_string")
        ))
        loop.close()
    threading.Thread(target=run, daemon=True).start()


@socketio.on("start_auto_scheduler")
def handle_start_auto(data):
    """Start the background daily auto-runner (random batch scheduler)."""
    global auto_runner_instance

    target_group = data.get("target_group", "").strip()
    delay_min    = float(data.get("delay_min", 30))
    delay_max    = float(data.get("delay_max", 60))

    if not target_group:
        socketio.emit("log", {"msg": "❌ Target group enter karo!", "type": "error"})
        return

    # Save config
    save_app_config({"target_group": target_group, "delay_min": delay_min, "delay_max": delay_max})

    # Stop existing if any
    if auto_runner_instance:
        auto_runner_instance.stop()

    accounts = load_all_accounts()
    if not accounts:
        socketio.emit("log", {"msg": "❌ Koi account nahi mila! sessions_config.json ya env vars set karo.", "type": "error"})
        return

    auto_runner_instance = DailyAutoRunner(target_group, delay_min, delay_max, socketio)
    auto_runner_instance.start()

    total_daily = sum(acc.get("daily_limit", 120) for acc in accounts)
    socketio.emit("log", {
        "msg": f"🤖 Auto-scheduler STARTED! {len(accounts)} accounts × 120/day = {total_daily} invites/day 🔥",
        "type": "success"
    })
    socketio.emit("scheduler_status", {"running": True, "accounts": len(accounts), "total_daily": total_daily})


@socketio.on("stop_auto_scheduler")
def handle_stop_auto():
    global auto_runner_instance
    if auto_runner_instance:
        auto_runner_instance.stop()
        socketio.emit("log", {"msg": "⛔ Auto-scheduler stopped.", "type": "warn"})
        socketio.emit("scheduler_status", {"running": False})


@socketio.on("start_invite")
def handle_invite(data):
    """Manual invite (without schedule - runs immediately)."""
    global invite_engine_instance
    state_manager = DailyStateManager()
    env_accounts  = load_all_accounts()
    accounts = get_available_accounts(state_manager) if env_accounts else data.get("accounts", [])

    if not accounts:
        socketio.emit("log", {"msg": "⚠️ All accounts at daily limit!", "type": "warn"})
        return

    invite_engine_instance = InviteEngine(
        accounts, data["target_group"],
        int(data.get("limit_per_account", 120)),
        float(data.get("delay_min", 30)),
        float(data.get("delay_max", 60)),
        socketio, None, state_manager
    )
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(invite_engine_instance.run())
        loop.close()
    threading.Thread(target=run, daemon=True).start()


@socketio.on("stop_invite")
def handle_stop():
    global invite_engine_instance
    if invite_engine_instance:
        invite_engine_instance.stop_flag.set()
        socketio.emit("log", {"msg": "⛔ Manual invite stopped.", "type": "warn"})


@socketio.on("get_accounts_status")
def handle_accounts_status():
    accounts_data, daily_summary = get_accounts_dashboard_data()
    socketio.emit("accounts_status", {"accounts": accounts_data, "daily": daily_summary})


@socketio.on("connect")
def handle_connect():
    """On client connect, send current scheduler status."""
    global auto_runner_instance
    is_running = bool(auto_runner_instance and
                      auto_runner_instance.thread and
                      auto_runner_instance.thread.is_alive())
    socketio.emit("scheduler_status", {"running": is_running})

    # Also send current account stats
    accounts_data, daily_summary = get_accounts_dashboard_data()
    socketio.emit("accounts_status", {"accounts": accounts_data, "daily": daily_summary})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Telegram Migration Tool running at http://0.0.0.0:{port}")
    all_accounts = load_all_accounts()
    print(f"📱 Loaded {len(all_accounts)} accounts")
    for acc in all_accounts:
        print(f"   → {acc.get('name', acc['phone'])} | limit: {acc.get('daily_limit', 120)}/day")

    # Auto-start scheduler if target group is configured
    cfg = load_app_config()
    if cfg.get("target_group") and all_accounts:
        auto_runner_instance = DailyAutoRunner(
            cfg["target_group"],
            cfg.get("delay_min", 30),
            cfg.get("delay_max", 60),
            socketio
        )
        auto_runner_instance.start()
        print(f"🤖 Auto-scheduler started for target: {cfg['target_group']}")

    socketio.run(app, host="0.0.0.0", port=port, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)
