import requests
from datetime import datetime, timedelta, timezone

# ══════════════════════════════════════════════════════════════════════
# CREDENTIALS & CONFIG
# ══════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = "YOUR_TELEGRAM_BOT_TOKEN"   # from @BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"              # your personal chat ID
GEMINI_API_KEY   = "YOUR_GEMINI_API_KEY"        # from aistudio.google.com
# ══════════════════════════════════════════════════════════════════════
# STEP 6 — Telegram human-in-the-loop approval
# ══════════════════════════════════════════════════════════════════════
def build_telegram_message(schedule_log):
    """
    Build a plain-text message (no Markdown) to avoid Telegram parse errors.
    Emojis and special characters work fine in plain text mode.
    """
    lines = ["Factory Production Schedule\n"]
    lines.append("=" * 50)
    lines.append("\nCONFLICT RESOLUTION:")
    lines.append("SO-005 (SmartHome IoT) deadline: Mar 8")
    lines.append("SO-003 (AgriBot) deadline: Mar 4 (first by EDF)\n")
    lines.append("FULL SCHEDULE:")
    for e in schedule_log:
        status = "OK" if e['on_time'] else "LATE"
        lines.append(
            f"{e['so_id']} | {e['product_id']} x{e['quantity']} | "
            f"{e['po_start'].strftime('%b %d')} to {e['po_end'].strftime('%b %d')} | "
            f"Deadline: {e['deadline'].strftime('%b %d')} [{status}]"
        )
    lines.append("\nREPLY OPTIONS:")
    lines.append("  'approve'            - Confirm with EDF policy")
    lines.append("  'reject'             - Cancel schedule")
    lines.append("  'schedule sjf'       - Shortest Job First")
    lines.append("  'schedule ljf'       - Longest Job First")
    lines.append("  'schedule priority'  - Naive Priority (demo)")
    lines.append("  'schedule slack'     - Slack Time")
    lines.append("  'schedule customer'  - Customer Tier (VIP)")
    return '\n'.join(lines)

def send_telegram(schedule_log):
    msg = build_telegram_message(schedule_log)

    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("\n⚠️  Telegram not configured — message preview:\n")
        print(msg)
        return

    import telegram, asyncio

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        try:
            # Send as plain text (no parse_mode) to avoid Markdown parsing issues
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=msg
            )
        except telegram.error.BadRequest as e:
            # Fallback: plain text (shouldn't happen now, but safe guard)
            print(f"   ⚠️  Message send error: {e}")
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=msg
                )
            except Exception as e2:
                print(f"   ❌ Failed to send Telegram message: {e2}")
                return
        
        try:
            await bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=open('gantt.png', 'rb')
            )
        except Exception as e:
            print(f"   ⚠️  Failed to send photo: {e}")
            
        print("✅ Telegram message sent")

    asyncio.run(_send())

def wait_for_approval():
    """
    Listen for approval/rejection or policy override via Telegram.
    
    Accepted responses:
      - 'approve'                      → proceed with current (EDF) policy
      - 'reject' / 'cancel'            → reject schedule
      - 'schedule sjf'                 → re-sort by Shortest Job First
      - 'schedule ljf'                 → re-sort by Longest Job First
      - 'schedule priority'            → re-sort by Priority (naive, for comparison)
      - 'schedule slack'               → re-sort by Slack Time
      - 'schedule customer'            → re-sort by Customer Tier
      - 'schedule [SO-0017, SO-0013]' → manual custom order (TODO)
    
    Returns:
      - (True, None)     → approved with current policy
      - (True, 'SJF')    → approved with new policy override
      - (False, None)    → rejected
    """
    import telegram
    import asyncio
    
    # Check if Telegram is configured
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("\n⏳ Awaiting terminal approval...")
        while True:
            response = input(
                "Approve/reject or select policy:\n"
                "  'approve' / 'reject'\n"
                "  'schedule [edf|sjf|ljf|priority|slack|customer]'\n> "
            ).strip().lower()
            
            if response == 'approve':
                print("✅ Schedule approved by planner (EDF).")
                return (True, None)
            elif response in ['reject', 'cancel']:
                print("❌ Schedule rejected by planner.")
                return (False, None)
            elif response.startswith('schedule '):
                parts = response.split()
                if len(parts) == 2:
                    policy = parts[1].upper()
                    if policy in ['EDF', 'SJF', 'LJF', 'PRIORITY', 'SLACK', 'CUSTOMER']:
                        print(f"✅ Schedule approved with {policy} policy override.")
                        return (True, policy)
                print("   Invalid format. Try: 'schedule sjf' or 'schedule priority'")
            else:
                print("   Please type 'approve', 'reject', or 'schedule [policy]'.")
    
    # Telegram is configured - use async polling
    async def _listen():
        """Listen for Telegram messages with approval/policy override (no timeout)."""
        try:
            bot = telegram.Bot(token=TELEGRAM_TOKEN)
        except Exception as e:
            print(f"❌ Failed to create Telegram bot: {e}", flush=True)
            return (False, None)
            
        print("\n⏳ Listening for Telegram approval (waiting indefinitely)...", flush=True)
        print("   Send 'approve' to continue, 'reject' to cancel,", flush=True)
        print("   or 'schedule [edf|sjf|ljf|priority|slack|customer]' to override policy.", flush=True)
        
        # First, skip all existing messages in the chat (only listen to NEW messages)
        try:
            existing_updates = await bot.get_updates(timeout=5)
            if existing_updates:
                # Set update_id to the last existing message + 1 to skip history
                update_id = existing_updates[-1].update_id + 1
                print(f"   (Skipped {len(existing_updates)} old message(s) from chat history)", flush=True)
            else:
                update_id = None
        except Exception as e:
            print(f"   ⚠️  Could not skip history: {e}", flush=True)
            update_id = None
        
        # Now listen for NEW messages only
        while True:
            try:
                # Poll for new messages (timeout=30 is for the request, not approval timeout)
                updates = await bot.get_updates(offset=update_id, timeout=30)
                
                if updates:
                    print(f"   Got {len(updates)} new update(s)", flush=True)
                
                for update in updates:
                    if update.message and update.message.text:
                        text = update.message.text.strip().lower()
                        print(f"   📱 Received: '{text}'", flush=True)
                        
                        # Check for approval
                        if text == 'approve':
                            print("✅ Schedule approved via Telegram (EDF).", flush=True)
                            return (True, None)
                        
                        # Check for rejection
                        elif text in ['reject', 'cancel']:
                            print("❌ Schedule rejected via Telegram.", flush=True)
                            return (False, None)
                        
                        # Check for policy override
                        elif text.startswith('schedule '):
                            parts = text.split()
                            if len(parts) == 2:
                                policy = parts[1].upper()
                                if policy in ['EDF', 'SJF', 'LJF', 'PRIORITY', 'SLACK', 'CUSTOMER']:
                                    print(f"✅ Schedule approved with {policy} policy override.", flush=True)
                                    return (True, policy)
                            print(f"   (Invalid policy. Accepted: edf|sjf|ljf|priority|slack|customer)", flush=True)
                        
                        else:
                            print(f"   (Waiting for 'approve'/'reject' or 'schedule [policy]', got '{text}')", flush=True)
                    
                    # Mark this update as processed
                    update_id = update.update_id + 1
                    
            except asyncio.TimeoutError:
                # Telegram request timed out, just retry
                print("   (polling...)", flush=True)
                continue
            except Exception as e:
                print(f"   ⚠️  Error listening to Telegram: {e}", flush=True)
                print("   Falling back to terminal input...", flush=True)
                # Fallback to terminal
                while True:
                    response = input(
                        "Type 'approve', 'reject', or 'schedule [policy]': "
                    ).strip().lower()
                    if response == 'approve':
                        return (True, None)
                    elif response in ['reject', 'cancel']:
                        return (False, None)
                    elif response.startswith('schedule '):
                        parts = response.split()
                        if len(parts) == 2:
                            policy = parts[1].upper()
                            if policy in ['EDF', 'SJF', 'LJF', 'PRIORITY', 'SLACK', 'CUSTOMER']:
                                return (True, policy)
                    print("   Invalid. Try: 'approve', 'reject', or 'schedule sjf'")
    
    # Run the async function and return its result
    try:
        print("Starting async listener...", flush=True)
        result = asyncio.run(_listen())
        print(f"Listener returned: {result}", flush=True)
        return result
    except Exception as e:
        print(f"❌ Error in wait_for_approval: {e}", flush=True)
        return (False, None)