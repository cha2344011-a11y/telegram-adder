"""
Daily Scheduler - Random Timing Throughout the Day
===================================================
- Each account: 120 invites/day in 8-12 random mini-batches
- Batches spread randomly from 8 AM to 11 PM
- Each account runs on its own independent schedule
- Midnight auto-reset to start fresh next day
- Late-start safe: if tool starts mid-day, remaining time is used
"""

import os
import json
import asyncio
import threading
import random
from datetime import datetime, date, timedelta

# ── Telethon imports (top-level to avoid late-import errors) ─────────────────
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPeerUser, InputChannel
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, UserAlreadyParticipantError,
    PeerFloodError, InputUserDeactivatedError,
    UserBannedInChannelError, UserNotMutualContactError
)

DATA_DIR         = "data"
SESSIONS_CONFIG  = "sessions_config.json"
DAILY_STATE_FILE = os.path.join(DATA_DIR, "daily_state.json")
SCHEDULE_FILE    = os.path.join(DATA_DIR, "today_schedule.json")
SCRAPED_FILE     = os.path.join(DATA_DIR, "scraped_members.csv")
INVITED_FILE     = os.path.join(DATA_DIR, "invited_members.csv")
FAILED_FILE      = os.path.join(DATA_DIR, "failed_members.csv")
PROGRESS_FILE    = os.path.join(DATA_DIR, "progress.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs("sessions", exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Daily State Manager
# ─────────────────────────────────────────────────────────────────────────────
class DailyStateManager:
    def __init__(self):
        self.state = self._load()

    def _load(self):
        today = str(date.today())
        if os.path.exists(DAILY_STATE_FILE):
            try:
                with open(DAILY_STATE_FILE) as f:
                    state = json.load(f)
                if state.get("date") != today:
                    return self._fresh_state(today)
                return state
            except Exception:
                pass
        return self._fresh_state(today)

    def _fresh_state(self, today):
        return {
            "date": today,
            "account_invites": {},
            "total_invited_today": 0,
            "total_invited_all_time": self._get_all_time_total(),
            "status": "idle"
        }

    def _get_all_time_total(self):
        if not os.path.exists(INVITED_FILE):
            return 0
        try:
            with open(INVITED_FILE, encoding="utf-8") as f:
                return max(0, sum(1 for _ in f) - 1)
        except Exception:
            return 0

    def save(self):
        try:
            with open(DAILY_STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    def get_account_today_count(self, phone):
        return self.state["account_invites"].get(phone, 0)

    def increment_account(self, phone, count=1):
        prev = self.state["account_invites"].get(phone, 0)
        self.state["account_invites"][phone]  = prev + count
        self.state["total_invited_today"]    += count
        self.state["total_invited_all_time"] += count
        self.save()

    def set_status(self, status):
        self.state["status"] = status
        self.save()

    def get_summary(self):
        return {
            "date":           self.state["date"],
            "total_today":    self.state["total_invited_today"],
            "total_all_time": self.state["total_invited_all_time"],
            "per_account":    self.state["account_invites"],
            "status":         self.state["status"]
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Account Loader
# ─────────────────────────────────────────────────────────────────────────────
def load_all_accounts():
    """Load accounts from sessions_config.json (local) or env vars (cloud)."""
    accounts = []

    if os.path.exists(SESSIONS_CONFIG):
        try:
            with open(SESSIONS_CONFIG, encoding="utf-8") as f:
                config = json.load(f)
            for acc in config.get("accounts", []):
                if acc.get("active", True):
                    accounts.append({
                        "api_id":         int(acc["api_id"]),
                        "api_hash":       acc["api_hash"],
                        "phone":          acc["phone"],
                        "session_string": acc.get("session_string"),
                        "daily_limit":    int(acc.get("daily_limit", 120)),
                        "name":           acc.get("name", acc["phone"])
                    })
        except Exception as e:
            print(f"[scheduler] Error reading sessions_config.json: {e}")
        return accounts

    # Cloud mode: env vars  API_ID_1, API_HASH_1, PHONE_1, SESSION_1, LIMIT_1
    i = 1
    while True:
        api_id = os.environ.get(f"API_ID_{i}")
        if not api_id:
            break
        accounts.append({
            "api_id":         int(api_id),
            "api_hash":       os.environ.get(f"API_HASH_{i}", ""),
            "phone":          os.environ.get(f"PHONE_{i}", ""),
            "session_string": os.environ.get(f"SESSION_{i}"),
            "daily_limit":    int(os.environ.get(f"LIMIT_{i}", "120")),
            "name":           os.environ.get(f"NAME_{i}", f"Account {i}")
        })
        i += 1

    return accounts


def get_available_accounts(state_manager):
    return [
        {**acc, "remaining_today": acc["daily_limit"] - state_manager.get_account_today_count(acc["phone"])}
        for acc in load_all_accounts()
        if acc["daily_limit"] - state_manager.get_account_today_count(acc["phone"]) > 0
    ]


def get_accounts_dashboard_data():
    state_manager = DailyStateManager()
    result = []
    for acc in load_all_accounts():
        phone      = acc["phone"]
        done_today = state_manager.get_account_today_count(phone)
        limit      = acc["daily_limit"]
        result.append({
            "phone":      phone,
            "name":       acc.get("name", phone),
            "done_today": done_today,
            "limit":      limit,
            "remaining":  max(0, limit - done_today),
            "pct":        round((done_today / limit) * 100) if limit else 0,
            "active":     done_today < limit
        })
    return result, state_manager.get_summary()


# ─────────────────────────────────────────────────────────────────────────────
#  Random Schedule Generator
#  120 invites → 8-12 batches spread randomly from now until 11 PM
#  FIXED: works correctly even when tool starts mid-day
# ─────────────────────────────────────────────────────────────────────────────
def generate_random_schedule(daily_limit=120, end_hour=23):
    """
    Split daily_limit invites into random-sized batches.
    Distributed between NOW and end_hour. Late-start safe.
    Returns list of dicts: {at, at_human, count, done}
    """
    now = datetime.now()
    today = now.date()
    end_dt = datetime(today.year, today.month, today.day, end_hour, 59, 59)

    # If it's already past end_hour, no batches for today
    if now >= end_dt:
        return []

    # Time window available (in seconds)
    available_seconds = int((end_dt - now).total_seconds())

    # Determine number of batches based on available time
    # Each batch needs ~15 min minimum gap (invites take time)
    max_batches = min(12, available_seconds // 900)  # 900s = 15 min
    num_batches = max(1, random.randint(
        max(1, max_batches - 3),
        max_batches
    ))

    if num_batches == 0:
        return []

    # Distribute invites unevenly (more natural)
    invite_counts = []
    remaining = daily_limit
    for i in range(num_batches - 1):
        min_this = max(5, remaining // (num_batches * 2))
        max_this = min(20, remaining - (num_batches - i - 1) * 5)
        if max_this < 5:
            invite_counts.append(remaining)
            remaining = 0
            break
        count = random.randint(min_this, max_this)
        invite_counts.append(count)
        remaining -= count
    if remaining > 0:
        invite_counts.append(remaining)

    # Pick random seconds offsets within available window
    # Ensure minimum 10-minute gaps between batches
    min_gap = 600  # 10 minutes minimum
    if available_seconds < min_gap * len(invite_counts):
        min_gap = available_seconds // max(1, len(invite_counts))

    offsets = sorted(random.sample(range(0, available_seconds, max(1, min_gap // 2)),
                                   min(len(invite_counts), available_seconds // max(1, min_gap // 2))))

    # Trim to match invite_counts length
    invite_counts = invite_counts[:len(offsets)]

    schedule = []
    for offset, count in zip(offsets, invite_counts):
        batch_time = now + timedelta(seconds=offset + random.randint(0, 300))
        if batch_time > end_dt:
            break
        schedule.append({
            "at":       batch_time.isoformat(),
            "at_human": batch_time.strftime("%I:%M %p"),
            "count":    count,
            "done":     False
        })

    return schedule


def save_today_schedule(schedules_by_account):
    try:
        with open(SCHEDULE_FILE, "w") as f:
            json.dump({"date": str(date.today()), "accounts": schedules_by_account},
                      f, indent=2, default=str)
    except Exception:
        pass


def load_today_schedule():
    today = str(date.today())
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE) as f:
                data = json.load(f)
            if data.get("date") == today:
                return data.get("accounts", {})
        except Exception:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
#  CSV Helpers (standalone, no import from engine to avoid circular imports)
# ─────────────────────────────────────────────────────────────────────────────
import csv

def _load_scraped_members():
    if not os.path.exists(SCRAPED_FILE):
        return []
    try:
        with open(SCRAPED_FILE, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def _load_processed_ids():
    done = set()
    for fpath in [INVITED_FILE, FAILED_FILE]:
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        done.add(row.get("user_id", ""))
            except Exception:
                pass
    return done

def _append_csv(fpath, row_dict):
    try:
        exists = os.path.exists(fpath)
        with open(fpath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row_dict.keys())
            if not exists:
                writer.writeheader()
            writer.writerow(row_dict)
    except Exception:
        pass

def _save_progress_file(invited, failed, remaining, total):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump({
                "invited": invited, "failed": failed,
                "remaining": remaining, "total": total,
                "timestamp": datetime.now().isoformat()
            }, f)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Telegram Client Factory
# ─────────────────────────────────────────────────────────────────────────────
def _make_client(api_id, api_hash, phone, session_string=None, proxy=None):
    if session_string:
        return TelegramClient(StringSession(session_string), api_id, api_hash, proxy=proxy)
    session_path = os.path.join("sessions", f"session_{phone}")
    return TelegramClient(session_path, api_id, api_hash, proxy=proxy)


# ─────────────────────────────────────────────────────────────────────────────
#  Daily Auto Runner
# ─────────────────────────────────────────────────────────────────────────────
class DailyAutoRunner:
    """
    Background thread that runs 24/7:
    - Generates a random daily schedule for each account on startup.
    - Fires invite batches silently at the scheduled times.
    - Auto-resets at midnight with a new schedule for the next day.
    """

    def __init__(self, target_group, delay_min, delay_max, socketio):
        self.target_group = target_group
        self.delay_min    = delay_min
        self.delay_max    = delay_max
        self.socketio     = socketio
        self.stop_flag    = threading.Event()
        self.thread       = None
        self.schedules    = {}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="AutoScheduler")
        self.thread.start()

    def stop(self):
        self.stop_flag.set()

    def is_running(self):
        return bool(self.thread and self.thread.is_alive() and not self.stop_flag.is_set())

    def _emit(self, event, data):
        try:
            self.socketio.emit(event, data)
        except Exception:
            pass

    def _build_schedule(self, force=False):
        """Build today's random schedule for each account. Reuse saved if same day."""
        accounts = load_all_accounts()
        saved    = load_today_schedule() if not force else {}
        new_schedules = {}

        for acc in accounts:
            phone = acc["phone"]
            name  = acc.get("name", phone)

            if phone in saved and not force:
                # Reuse existing schedule for today
                entry = saved[phone]
                # Make sure the account dict is up to date
                entry["account"] = acc
                new_schedules[phone] = entry
            else:
                limit   = acc.get("daily_limit", 120)
                batches = generate_random_schedule(limit)
                new_schedules[phone] = {
                    "account": acc,
                    "batches": batches
                }

            pending = [b for b in new_schedules[phone]["batches"] if not b["done"]]
            if pending:
                times_str = ", ".join(b["at_human"] for b in pending[:4])
                self._emit("log", {
                    "msg": f"📅 {name}: {len(pending)} batches today → {times_str}{'...' if len(pending) > 4 else ''}",
                    "type": "info"
                })
            else:
                self._emit("log", {"msg": f"📅 {name}: All done for today or too late to start.", "type": "warn"})

        self.schedules = new_schedules
        save_today_schedule(new_schedules)

    def _run_loop(self):
        """Main background loop — checks every 60s for due batches."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self._build_schedule()
        accounts = load_all_accounts()
        total_daily = sum(acc.get("daily_limit", 120) for acc in accounts)
        self._emit("log", {
            "msg": f"🤖 Auto-Scheduler LIVE! {len(accounts)} accounts → {total_daily} invites/day 🔥",
            "type": "success"
        })

        while not self.stop_flag.is_set():
            now               = datetime.now()
            today_str         = str(date.today())
            tomorrow_midnight = datetime(now.year, now.month, now.day) + timedelta(days=1)

            # Midnight reset
            if now >= tomorrow_midnight:
                self._emit("log", {"msg": "🌙 New day! Generating fresh schedule...", "type": "info"})
                self._build_schedule(force=True)
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                continue

            # Check each account's schedule for due batches
            for phone, data in list(self.schedules.items()):
                if self.stop_flag.is_set():
                    break

                acc     = data.get("account", {})
                batches = data.get("batches", [])
                name    = acc.get("name", phone)

                for batch in batches:
                    if batch["done"]:
                        continue

                    batch_time = datetime.fromisoformat(batch["at"])

                    if batch_time <= now:
                        # Mark done FIRST to avoid double-fire
                        batch["done"] = True
                        save_today_schedule(self.schedules)

                        # Check daily quota
                        state = DailyStateManager()
                        done_today = state.get_account_today_count(phone)
                        limit      = acc.get("daily_limit", 120)

                        if done_today >= limit:
                            self._emit("log", {"msg": f"✅ {name} already at limit ({limit}/day). Skipping.", "type": "info"})
                            break

                        actual_count = min(batch["count"], limit - done_today)
                        self._emit("log", {
                            "msg": f"⏰ [{batch['at_human']}] Batch firing: {actual_count} invites via {name}",
                            "type": "info"
                        })

                        try:
                            loop.run_until_complete(
                                self._fire_batch(acc, actual_count, batch["at_human"])
                            )
                        except Exception as e:
                            self._emit("log", {"msg": f"❌ Batch error ({name}): {e}", "type": "error"})

                        break  # One batch per account per loop tick

            # Sleep 60 seconds before next check
            self.stop_flag.wait(timeout=60)

        loop.close()
        self._emit("log", {"msg": "🛑 Auto-Scheduler stopped.", "type": "warn"})

    async def _fire_batch(self, acc, count, time_label):
        """Invite `count` pending members using this account."""
        phone  = acc.get("phone", "")
        name   = acc.get("name", phone)

        all_members = _load_scraped_members()
        processed   = _load_processed_ids()
        pending     = [m for m in all_members if m.get("user_id", "") not in processed]

        total = len(all_members)

        if not pending:
            self._emit("log", {"msg": "🎉 All members already invited!", "type": "success"})
            return

        client = _make_client(
            acc["api_id"], acc["api_hash"], phone, acc.get("session_string")
        )
        invited_count = 0

        try:
            await client.connect()

            if not await client.is_user_authorized():
                self._emit("log", {"msg": f"❌ {name} not authorized! Run bulk_session_generator.py again.", "type": "error"})
                return

            target_entity = await client.get_entity(self.target_group)
            target_input  = InputChannel(target_entity.id, target_entity.access_hash)

            state = DailyStateManager()

            for _ in range(count):
                if not pending or self.stop_flag.is_set():
                    break

                member = pending.pop(0)
                uid    = member.get("user_id", "")
                uname  = member.get("username") or f"id:{uid}"

                try:
                    if member.get("username"):
                        user_to_add = await client.get_input_entity(member["username"])
                    else:
                        user_to_add = InputPeerUser(int(uid), int(member.get("access_hash", 0)))

                    await client(InviteToChannelRequest(target_input, [user_to_add]))

                    invited_count += 1
                    state.increment_account(phone, 1)

                    _append_csv(INVITED_FILE, {
                        "user_id":    uid,
                        "username":   member.get("username", ""),
                        "first_name": member.get("first_name", ""),
                        "last_name":  member.get("last_name", ""),
                        "account":    phone,
                        "timestamp":  datetime.now().isoformat()
                    })

                    summary = state.get_summary()
                    self._emit("log", {
                        "msg": f"✅ [{name}] Invited: {uname} (batch: {invited_count}/{count})",
                        "type": "success"
                    })
                    self._emit("invite_progress", {
                        "invited":   summary["total_all_time"],
                        "remaining": len(pending),
                        "total":     total,
                        "failed":    0
                    })
                    self._emit("daily_update", summary)
                    _save_progress_file(summary["total_all_time"], 0, len(pending), total)

                except FloodWaitError as e:
                    wait = e.seconds + random.randint(5, 15)
                    self._emit("log", {"msg": f"⏳ FloodWait {wait}s on {name}...", "type": "warn"})
                    await asyncio.sleep(wait)
                    pending.insert(0, member)  # retry
                    continue

                except UserAlreadyParticipantError:
                    pass  # silently skip

                except (UserPrivacyRestrictedError, InputUserDeactivatedError,
                        UserBannedInChannelError, UserNotMutualContactError, ValueError) as e:
                    _append_csv(FAILED_FILE, {
                        "user_id":   uid,
                        "username":  member.get("username", ""),
                        "reason":    "Privacy/Invalid_ID",
                        "timestamp": datetime.now().isoformat()
                    })

                except PeerFloodError:
                    self._emit("log", {"msg": f"🔴 PeerFlood on {name}! Stopping this batch early.", "type": "error"})
                    break

                except Exception as ex:
                    self._emit("log", {"msg": f"❌ {uname}: {ex}", "type": "error"})

                # Random delay between invites
                delay = random.uniform(self.delay_min, self.delay_max)
                await asyncio.sleep(delay)

        except Exception as ex:
            self._emit("log", {"msg": f"❌ {name} connection error: {ex}", "type": "error"})
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        done_today = DailyStateManager().get_account_today_count(phone)
        limit      = acc.get("daily_limit", 120)
        self._emit("log", {
            "msg": f"✔️ [{name}] Batch done: +{invited_count} invited. Today: {done_today}/{limit}",
            "type": "success"
        })
        self._emit("account_update", get_accounts_dashboard_data()[0])
