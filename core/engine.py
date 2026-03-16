"""
Telegram Migration Engine
=========================
- scrape_members(): Fetch all members from source group → CSV
- InviteEngine:     Manual multi-account invite (non-scheduled)
"""

import os
import asyncio
import csv
import json
import random
import threading
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch, InputPeerUser, InputChannel
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, UserAlreadyParticipantError,
    PeerFloodError, InputUserDeactivatedError,
    UserBannedInChannelError, UserNotMutualContactError
)

DATA_DIR     = "data"
SESSIONS_DIR = "sessions"
os.makedirs(DATA_DIR,     exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)

SCRAPED_FILE  = os.path.join(DATA_DIR, "scraped_members.csv")
INVITED_FILE  = os.path.join(DATA_DIR, "invited_members.csv")
FAILED_FILE   = os.path.join(DATA_DIR, "failed_members.csv")
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _make_client(api_id, api_hash, phone, session_string=None, proxy=None):
    if session_string:
        return TelegramClient(StringSession(session_string), int(api_id), api_hash, proxy=proxy)
    session_path = os.path.join(SESSIONS_DIR, f"session_{phone}")
    return TelegramClient(session_path, int(api_id), api_hash, proxy=proxy)


def _load_scraped():
    if not os.path.exists(SCRAPED_FILE):
        return []
    with open(SCRAPED_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


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
    exists = os.path.exists(fpath)
    with open(fpath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row_dict.keys())
        if not exists:
            writer.writeheader()
        writer.writerow(row_dict)


def _save_progress(invited, failed, remaining, total):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "invited": invited, "failed": failed,
            "remaining": remaining, "total": total,
            "timestamp": datetime.now().isoformat()
        }, f)


# ─────────────────────────────────────────────────────────────────────────────
#  SCRAPER
# ─────────────────────────────────────────────────────────────────────────────
async def scrape_members(api_id, api_hash, phone, source_group, socketio, session_string=None):
    """
    Scrape all visible members from source_group.
    Saves to scraped_members.csv for later use by InviteEngine / DailyAutoRunner.
    """
    client = _make_client(api_id, api_hash, phone, session_string)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        socketio.emit("otp_required", {"phone": phone})
        otp_file = f"otp_{phone}.tmp"
        for _ in range(120):
            await asyncio.sleep(1)
            if os.path.exists(otp_file):
                with open(otp_file) as f:
                    code = f.read().strip()
                os.remove(otp_file)
                try:
                    await client.sign_in(phone, code)
                except Exception as e:
                    if "password" in str(e).lower():
                        # 2FA: handled separately via another OTP endpoint
                        socketio.emit("log", {"msg": "2FA account: password required.", "type": "warn"})
                break

    try:
        entity = await client.get_entity(source_group)
    except Exception as e:
        socketio.emit("log", {"msg": f"❌ Group not found: {e}", "type": "error"})
        await client.disconnect()
        return 0

    socketio.emit("log", {"msg": f"✅ Connected to: {entity.title}", "type": "success"})

    all_participants = []
    offset, limit   = 0, 200

    while True:
        try:
            result = await client(GetParticipantsRequest(
                entity, ChannelParticipantsSearch(""),
                offset=offset, limit=limit, hash=0
            ))
        except FloodWaitError as e:
            socketio.emit("log", {"msg": f"⏳ FloodWait {e.seconds}s...", "type": "warn"})
            await asyncio.sleep(e.seconds)
            continue
        except Exception as e:
            socketio.emit("log", {"msg": f"❌ Error fetching participants: {e}", "type": "error"})
            break

        if not result.users:
            break

        all_participants.extend(result.users)
        offset += len(result.users)
        socketio.emit("scrape_progress", {
            "scraped": len(all_participants),
            "msg": f"Scraped {len(all_participants)} members..."
        })
        if len(result.users) < limit:
            break
        await asyncio.sleep(0.5)

    # Save to CSV
    saved = 0
    with open(SCRAPED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "first_name", "last_name", "access_hash"])
        for u in all_participants:
            if u.bot or u.deleted or not u.username:
                continue
            writer.writerow([
                u.id, u.username,
                u.first_name or "", u.last_name or "",
                u.access_hash
            ])
            saved += 1

    socketio.emit("log", {"msg": f"✅ Scraping done! {saved} members saved.", "type": "success"})
    socketio.emit("scrape_done", {"total": saved})
    await client.disconnect()
    return saved


# ─────────────────────────────────────────────────────────────────────────────
#  MANUAL INVITE ENGINE  (non-scheduled, runs immediately on demand)
# ─────────────────────────────────────────────────────────────────────────────
class InviteEngine:
    """
    Manual invite runner — uses all available accounts immediately.
    Respects per-account daily limits via state_manager if provided.
    """

    def __init__(self, accounts, target_group, limit_per_account,
                 delay_min, delay_max, socketio, proxy=None, state_manager=None):
        self.accounts          = accounts
        self.target_group      = target_group
        self.limit_per_account = int(limit_per_account)
        self.delay_min         = float(delay_min)
        self.delay_max         = float(delay_max)
        self.socketio          = socketio
        self.proxy             = proxy
        self.state_manager     = state_manager
        self.stop_flag         = threading.Event()

    def _emit(self, event, data):
        try:
            self.socketio.emit(event, data)
        except Exception:
            pass

    async def run(self):
        all_members = _load_scraped()
        processed   = _load_processed_ids()
        pending     = [m for m in all_members if m.get("user_id", "") not in processed]

        total     = len(all_members)
        invited   = len(all_members) - len(pending)
        failed    = 0
        remaining = len(pending)

        self._emit("log", {"msg": f"📋 Total: {total} | Pending: {remaining} | Accounts: {len(self.accounts)}", "type": "info"})

        if not pending:
            self._emit("log", {"msg": "✅ All members already processed!", "type": "success"})
            return

        for acc in self.accounts:
            if not pending or self.stop_flag.is_set():
                break

            phone          = acc.get("phone", "")
            name           = acc.get("name", phone)
            session_string = acc.get("session_string")

            # Determine today's remaining quota for this account
            if self.state_manager:
                done_today    = self.state_manager.get_account_today_count(phone)
                acc_limit     = acc.get("daily_limit", self.limit_per_account)
                acc_remaining = max(0, acc_limit - done_today)
            else:
                acc_remaining = acc.get("remaining_today", self.limit_per_account)

            if acc_remaining <= 0:
                self._emit("log", {"msg": f"⏭️ {name} daily quota full. Skipping.", "type": "warn"})
                continue

            self._emit("log", {"msg": f"📱 Using: {name} | Quota left: {acc_remaining}", "type": "info"})

            client = _make_client(acc["api_id"], acc["api_hash"], phone, session_string, self.proxy)

            try:
                await client.connect()
                if not await client.is_user_authorized():
                    self._emit("log", {"msg": f"❌ {name} not authorized. Run session_generator.py.", "type": "error"})
                    continue

                target_entity = await client.get_entity(self.target_group)
                target_input  = InputChannel(target_entity.id, target_entity.access_hash)
                acc_count     = 0

                while pending and acc_count < acc_remaining and not self.stop_flag.is_set():
                    member = pending.pop(0)
                    uid    = member.get("user_id", "")
                    uname  = member.get("username") or f"id:{uid}"

                    try:
                        if member.get("username"):
                            user_to_add = await client.get_input_entity(member["username"])
                        else:
                            user_to_add = InputPeerUser(int(uid), int(member.get("access_hash", 0)))

                        await client(InviteToChannelRequest(target_input, [user_to_add]))

                        invited   += 1
                        acc_count += 1
                        remaining  = len(pending)

                        if self.state_manager:
                            self.state_manager.increment_account(phone, 1)

                        _append_csv(INVITED_FILE, {
                            "user_id":    uid, "username": member.get("username", ""),
                            "first_name": member.get("first_name", ""),
                            "last_name":  member.get("last_name", ""),
                            "account":    phone, "timestamp": datetime.now().isoformat()
                        })
                        self._emit("log", {
                            "msg": f"✅ [{name}] {uname} ({acc_count}/{acc_remaining})",
                            "type": "success"
                        })
                        self._emit("invite_progress", {
                            "invited": invited, "failed": failed,
                            "remaining": remaining, "total": total
                        })
                        _save_progress(invited, failed, remaining, total)

                    except FloodWaitError as e:
                        wait = e.seconds + 5
                        self._emit("log", {"msg": f"⏳ FloodWait {wait}s...", "type": "warn"})
                        await asyncio.sleep(wait)
                        pending.insert(0, member)
                        continue

                    except UserAlreadyParticipantError:
                        pass

                    except (UserPrivacyRestrictedError, InputUserDeactivatedError,
                            UserBannedInChannelError, UserNotMutualContactError, ValueError) as e:
                        failed += 1
                        _append_csv(FAILED_FILE, {
                            "user_id": uid, "username": member.get("username", ""),
                            "reason": "Privacy/Invalid_ID", "timestamp": datetime.now().isoformat()
                        })

                    except PeerFloodError:
                        self._emit("log", {"msg": f"🔴 PeerFlood on {name}! Rotating...", "type": "error"})
                        pending.insert(0, member)
                        break

                    except Exception as ex:
                        failed += 1
                        _append_csv(FAILED_FILE, {
                            "user_id": uid, "username": member.get("username", ""),
                            "reason": str(ex)[:120], "timestamp": datetime.now().isoformat()
                        })

                    delay = random.uniform(self.delay_min, self.delay_max)
                    await asyncio.sleep(delay)

            except Exception as ex:
                self._emit("log", {"msg": f"❌ {name} fatal error: {ex}", "type": "error"})
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        status = "stopped" if self.stop_flag.is_set() else "done"
        self._emit("log", {
            "msg": f"🎉 {'Stopped' if self.stop_flag.is_set() else 'Done'}! ✅ {invited} invited | ❌ {failed} failed | 📋 {remaining} remaining",
            "type": "warn" if self.stop_flag.is_set() else "success"
        })
        self._emit("invite_done", {"invited": invited, "failed": failed, "remaining": remaining, "total": total})
        _save_progress(invited, failed, remaining, total)
