from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty, InputPeerChannel, InputPeerUser
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError
from telethon.tl.functions.channels import InviteToChannelRequest
import sys
import csv
import traceback
import time
import random
import os

print("--- Telegram Group Member Transfer Tool ---")
print("Warning: Bulk adding users can result in account ban due to Telegram's anti-spam policies.")

api_id_input = input("Enter API ID: ")
api_hash = input("Enter API Hash: ")
phone = input("Enter Phone Number (with country code, e.g., +919876543210): ")

client = TelegramClient(f'session_{phone}', int(api_id_input), api_hash)
client.connect()

if not client.is_user_authorized():
    client.send_code_request(phone)
    client.sign_in(phone, input('Enter the code you received on Telegram: '))

def scrape_users():
    chats = []
    last_date = None
    chunk_size = 200
    groups = []
    
    result = client(GetDialogsRequest(
                 offset_date=last_date,
                 offset_id=0,
                 offset_peer=InputPeerEmpty(),
                 limit=chunk_size,
                 hash=0
             ))
    chats.extend(result.chats)
    
    for chat in chats:
        try:
            # Check if it's a supergroup (megagroup)
            if hasattr(chat, 'megagroup') and chat.megagroup:
                groups.append(chat)
        except Exception:
            continue
            
    print('\nChoose a group to scrape members from:')
    for i, g in enumerate(groups):
        print(f"{i} - {g.title}")
        
    g_index = int(input("\nEnter the number of the group: "))
    target_group = groups[g_index]
    
    print('Fetching Members (This might take a while for large groups)...')
    all_participants = client.get_participants(target_group, aggressive=True)
    
    print('Saving to file...')
    with open("members.csv", "w", encoding='UTF-8', newline='') as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(['username', 'user id', 'access hash', 'name', 'group', 'group id'])
        for user in all_participants:
            username = user.username if user.username else ""
            first_name = user.first_name if user.first_name else ""
            last_name = user.last_name if user.last_name else ""
            name = (first_name + ' ' + last_name).strip()
            writer.writerow([username, user.id, user.access_hash, name, target_group.title, target_group.id])
            
    print('Members scraped and saved to members.csv successfully!')

def add_users():
    if not os.path.exists("members.csv"):
        print("members.csv missing! Please scrape users first (Option 1).")
        return

    users = []
    with open("members.csv", encoding='UTF-8') as f:
        rows = csv.reader(f, delimiter=",")
        next(rows, None) # skip header
        for row in rows:
            user = {
                'username': row[0],
                'id': int(row[1]),
                'access_hash': int(row[2]),
                'name': row[3]
            }
            users.append(user)
            
    chats = []
    last_date = None
    chunk_size = 200
    groups = []
    
    result = client(GetDialogsRequest(
                 offset_date=last_date,
                 offset_id=0,
                 offset_peer=InputPeerEmpty(),
                 limit=chunk_size,
                 hash=0
             ))
    chats.extend(result.chats)
    
    for chat in chats:
        try:
            if hasattr(chat, 'megagroup') and chat.megagroup:
                groups.append(chat)
        except Exception:
            continue
            
    print('\nChoose the target group to add members to:')
    for i, group in enumerate(groups):
        print(f"{i} - {group.title}")
        
    g_index = int(input("\nEnter the number of the group: "))
    target_group = groups[g_index]
    target_group_entity = InputPeerChannel(target_group.id, target_group.access_hash)
    
    print('\n1. Add by Username')
    print('2. Add by User ID')
    mode = int(input("Enter choice (1 or 2): "))
    
    n = 0
    for user in users:
        n += 1
        # IMPORTANT: Pausing heavily to prevent instant ban
        if n % 40 == 0:
            print("Pauing for 15 minutes to avoid FloodWait restriction...")
            time.sleep(900)
            
        try:
            identifier = user['username'] if user['username'] else str(user['id'])
            print(f"Adding user: {identifier}")
            
            if mode == 1:
                if not user['username']:
                    continue
                user_to_add = client.get_input_entity(user['username'])
            elif mode == 2:
                user_to_add = InputPeerUser(user['id'], user['access_hash'])
            else:
                sys.exit("Invalid Mode Selected.")
            
            client(InviteToChannelRequest(target_group_entity, [user_to_add]))
            
            # Random delay between requests is vital
            delay = random.randrange(15, 30)
            print(f"Success! Waiting {delay} seconds before next add...")
            time.sleep(delay)
            
        except PeerFloodError:
            print("\n[!] Telegram Flood Error! This account can't add more users right now.")
            print("Stopping script. Try again after 24 hours or use another account.")
            break
        except UserPrivacyRestrictedError:
            print("User's privacy settings blocked the invite. Skipping.")
        except Exception as e:
            print(f"Error: {e}")
            continue

print("""
1. Scrape (Download) users from old group
2. Add users to new group
""")
choice = input("Enter choice (1 or 2): ")

if choice == '1':
    scrape_users()
elif choice == '2':
    add_users()
else:
    print("Invalid choice.")
