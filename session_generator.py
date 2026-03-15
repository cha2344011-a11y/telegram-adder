"""
Run this script LOCALLY on your computer to generate a StringSession.
You only need to do this ONCE per Telegram account.
The output string is then pasted as an Environment Variable on Render.

Usage:
  python session_generator.py
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

async def generate():
    print("=" * 50)
    print("  Telegram StringSession Generator")
    print("  Run this ONCE locally, then paste the")
    print("  output string to Render env variables.")
    print("=" * 50)

    api_id   = int(input("\nEnter API ID   : "))
    api_hash = input("Enter API Hash : ").strip()
    phone    = input("Enter Phone (+91...): ").strip()

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.send_code_request(phone)
        code = input("Enter the OTP you received on Telegram: ").strip()
        await client.sign_in(phone, code)

        session_string = client.session.save()

    print("\n" + "=" * 50)
    print("✅ YOUR STRING SESSION (copy this):")
    print("=" * 50)
    print(session_string)
    print("=" * 50)
    print("\nPaste this as an Environment Variable on Render:")
    print(f'  Key  : SESSION_1')
    print(f'  Value: (the long string above)')
    print("\nFor multiple accounts, use SESSION_1, SESSION_2, etc.")
    print("Also add API_ID_1, API_HASH_1, PHONE_1 etc.\n")

asyncio.run(generate())
