"""
BULK SESSION GENERATOR
======================
Ek baar run karo - sab 8-9 accounts ke StringSessions generate ho jayenge.
Output ek 'sessions_config.json' file mein save hoga.

Local pe run karo:
  python bulk_session_generator.py
"""

import asyncio
import json
import os
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession

OUTPUT_FILE = "sessions_config.json"

async def generate_single(index, api_id, api_hash, phone):
    print(f"\n{'='*50}")
    print(f"  Account {index}: {phone}")
    print(f"{'='*50}")

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    try:
        await client.send_code_request(phone)
        print(f"📲 OTP bheja gaya {phone} pe")
        code = input(f"Account {index} ka OTP enter karo: ").strip()

        try:
            await client.sign_in(phone, code)
        except Exception as e:
            if "2FA" in str(e) or "password" in str(e).lower():
                password = input(f"Account {index} ka 2FA password enter karo: ").strip()
                await client.sign_in(password=password)
            else:
                raise e

        session_string = client.session.save()
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        print(f"✅ Account {index} login successful! Name: {name}")
        return {
            "index": index,
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "session_string": session_string,
            "name": name,
            "daily_limit": 120,   # 120 invites per account per day
            "active": True
        }
    except Exception as e:
        print(f"❌ Account {index} error: {e}")
        return None
    finally:
        await client.disconnect()

async def main():
    print("\n" + "🔥" * 25)
    print("  BULK SESSION GENERATOR")
    print("  Telegram Migration Tool - Pro")
    print("🔥" * 25)

    num = int(input("\nKitne accounts hain? (e.g. 8): "))

    # Common API credentials check
    print("\n" + "-"*50)
    print("Kya sab accounts ke liye ek hi API ID/Hash hai?")
    print("(Agar haan toh ek baar enter karo)")
    same_api = input("Haan (h) / Nahi (n): ").strip().lower()

    common_api_id   = None
    common_api_hash = None

    if same_api == 'h':
        common_api_id   = int(input("Common API ID   : "))
        common_api_hash = input("Common API Hash : ").strip()

    accounts = []
    for i in range(1, num + 1):
        print(f"\n--- Account {i}/{num} ---")

        if same_api == 'h':
            api_id   = common_api_id
            api_hash = common_api_hash
        else:
            api_id   = int(input(f"Account {i} API ID   : "))
            api_hash = input(f"Account {i} API Hash : ").strip()

        phone = input(f"Account {i} Phone (+91...): ").strip()

        result = await generate_single(i, api_id, api_hash, phone)
        if result:
            accounts.append(result)
        else:
            print(f"⚠️  Account {i} skip kiya gaya.")

        # Delay between accounts to avoid rate limits
        if i < num:
            print("\n⏳ Next account ke liye 5 seconds wait...")
            await asyncio.sleep(5)

    # Save to JSON
    config = {
        "accounts": accounts,
        "total_accounts": len(accounts),
        "created_at": datetime.now().isoformat()
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n{'✅'*20}")
    print(f"  {len(accounts)} accounts successfully configured!")
    print(f"  Saved to: {OUTPUT_FILE}")
    print(f"{'✅'*20}")

    # Print Render env vars
    print("\n📋 RENDER ENVIRONMENT VARIABLES (copy-paste karo):")
    print("-" * 60)
    for acc in accounts:
        idx = acc['index']
        print(f"API_ID_{idx}   = {acc['api_id']}")
        print(f"API_HASH_{idx} = {acc['api_hash']}")
        print(f"PHONE_{idx}    = {acc['phone']}")
        print(f"SESSION_{idx}  = {acc['session_string'][:30]}...")
        print()

asyncio.run(main())
