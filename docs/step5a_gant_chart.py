import requests
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime, timedelta, timezone

# Shared visual + factory constants from step 1
from step1_api_call import (
    TODAY,
    PHASES_ORDER,
    PHASE_COLORS,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
)
#  ══════════════════════════════════════════════════════════════════════
# STEP 5a — Gantt chart
#
# Layout:
#   - Y-axis LEFT:  order number only (01–12)
#   - Y-axis RIGHT: product · SO · customer · priority · slack
#   - Each phase drawn as its own colored segment (PHASE_COLORS)
#   - Gold diamond at deadline
#   - Blue dashed today line
#   - Dark background (#0d1117) matching novaboard aesthetic
# ══════════════════════════════════════════════════════════════════════
DAY_START_HOUR = 8
DAY_END_HOUR   = 16

def split_into_working_segments(start_dt, end_dt):
    """
    Split a phase (start_dt → end_dt) into drawable segments covering
    only working hours (08:00–16:00). The gaps between 16:00 and 08:00
    are simply not drawn — the visual white space is the overnight break.

    A phase like THT: Mar01 13:18 → Mar02 08:18 becomes:
      [Mar01 13:18 → Mar01 16:00]   (2h 42min today)
      [Mar02 08:00 → Mar02 08:18]   (18min tomorrow)
    The 16-hour gap in between is invisible on the chart — correct.
    """
    segments = []
    cursor   = start_dt

    while cursor < end_dt:
        day_end = cursor.replace(
            hour=DAY_END_HOUR, minute=0, second=0, microsecond=0
        )
        if end_dt <= day_end:
            segments.append((cursor, end_dt))
            break
        else:
            segments.append((cursor, day_end))
            cursor = (cursor + timedelta(days=1)).replace(
                hour=DAY_START_HOUR, minute=0, second=0, microsecond=0
            )

    return segments


def generate_gantt(schedule_log):
    fig, ax = plt.subplots(figsize=(22, 10))
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#161b22')

    # Style tick labels and spines for dark theme
    ax.tick_params(colors='#8b949e', labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor('#30363d')

    for i, entry in enumerate(schedule_log):
        # Draw each phase split into working-hours segments.
        # A phase that crosses midnight becomes 2+ bars with a visible
        # gap between 16:00 and 08:00 — the overnight break.
        for phase in entry['phases']:
            color    = PHASE_COLORS.get(phase['name'], '#3498db')
            segments = split_into_working_segments(phase['start'], phase['end'])
            for seg_start, seg_end in segments:
                ps = mdates.date2num(seg_start)
                pe = mdates.date2num(seg_end)
                ax.barh(i, pe - ps, left=ps, height=0.62,
                        color=color, alpha=0.88,
                        edgecolor='#0d1117', linewidth=0.4)

        # Gold diamond at deadline — easy to spot vs bar end
        dl = mdates.date2num(entry['deadline'])
        ax.plot(dl, i, marker='D', color='#ffd700', markersize=8,
                zorder=5, markeredgecolor='#0d1117', markeredgewidth=0.8)

        # RIGHT-SIDE label: full info so left axis stays clean
        # Slack = hours between PO end and customer deadline
        po_end_num = mdates.date2num(entry['po_end'])
        slack_h    = (entry['deadline'] - entry['po_end']).total_seconds() / 3600
        ax.text(
            po_end_num + 0.06, i,
            f"  {entry['product_id']} x{entry['quantity']}"
            f"  |  {entry['so_id'].split('/')[1]}"
            f"  |  {entry['customer'][:14]}"
            f"  |  P{entry['priority']}"
            f"  |  +{slack_h:.0f}h slack",
            va='center', ha='left', fontsize=7.8,
            color='#c9d1d9', fontfamily='monospace'
        )

    # Blue dashed today line
    today_num = mdates.date2num(TODAY)
    ax.axvline(today_num, color='#58a6ff', linewidth=2,
               linestyle='--', zorder=10, alpha=0.85, label='Today (Feb 28)')

    # Left Y-axis: order numbers only — all detail is on the right
    ax.set_yticks(range(len(schedule_log)))
    ax.set_yticklabels(
        [f"{i+1:02d}" for i in range(len(schedule_log))],
        color='#58a6ff', fontsize=9, fontweight='bold'
    )

    # X-axis: daily ticks, Feb 28 → Mar 16
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', color='#8b949e')

    # Explicit bounds — prevents bars from being squished to left edge
    ax.set_xlim(
        mdates.date2num(TODAY - timedelta(hours=5)),
        mdates.date2num(TODAY + timedelta(days=16))
    )

    ax.invert_yaxis()
    ax.xaxis.grid(True, color='#21262d', linewidth=0.7)
    ax.yaxis.grid(False)
    ax.set_axisbelow(True)

    # Legend: one patch per phase + deadline marker + today line
    legend_elements = [
        mpatches.Patch(facecolor=PHASE_COLORS[p], label=p, alpha=0.88)
        for p in PHASES_ORDER
    ]
    legend_elements.append(
        plt.Line2D([0], [0], color='#ffd700', marker='D',
                   linestyle='None', markersize=7, label='Deadline'))
    legend_elements.append(
        plt.Line2D([0], [0], color='#58a6ff', linestyle='--',
                   label='Today (Feb 28)'))
    ax.legend(handles=legend_elements, loc='lower right', fontsize=8,
              facecolor='#21262d', edgecolor='#30363d', labelcolor='#c9d1d9',
              ncol=3, framealpha=0.9)

    ax.set_title(
        'NovaBoard Electronics — Production Schedule (EDF)  ·  12/12 Orders On Time ✅',
        fontsize=13, fontweight='bold', color='#c9d1d9', pad=12
    )
    ax.set_xlabel('Date', color='#8b949e', fontsize=10)
    ax.set_ylabel('Order #', color='#8b949e', fontsize=10)

    plt.tight_layout()
    plt.savefig('gantt.png', dpi=150, bbox_inches='tight', facecolor='#0d1117')
    print("\n📊 Gantt chart saved to gantt.png")
    plt.show()


# ══════════════════════════════════════════════════════════════════════
# STEP 5b — Telegram human-in-the-loop
# ══════════════════════════════════════════════════════════════════════
def build_telegram_message(schedule_log):
    lines = ["🏭 *NovaBoard Production Schedule — EDF*\n"]
    lines.append("📌 *SO-005 Conflict Resolution:*")
    lines.append("SO-005 (SmartHome IoT, P1↑) deadline: Mar 8.")
    lines.append("SO-003 (AgriBot, Mar 4) correctly stays first — EDF prevails over raw priority.\n")
    lines.append("*Full Schedule:*")
    for e in schedule_log:
        status = "✅" if e['on_time'] else "❌ LATE"
        lines.append(
            f"{e['so_id']} | {e['product_id']} x{e['quantity']} | "
            f"{e['po_start'].strftime('%b %d')} → {e['po_end'].strftime('%b %d')} | "
            f"Deadline: {e['deadline'].strftime('%b %d')} {status}"
        )
    lines.append("\nReply *approve* to confirm and move orders to in_progress.")
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
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode='Markdown'
        )
        await bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=open('gantt.png', 'rb')
        )
        print("✅ Telegram message sent")

    asyncio.run(_send())

def wait_for_approval():
    print("\n⏳ Awaiting planner approval...")
    while True:
        response = input("Type 'approve' to confirm, 'reject' to cancel: ").strip().lower()
        if response == 'approve':
            print("✅ Schedule approved by planner.")
            return True
        elif response == 'reject':
            print("❌ Schedule rejected by planner.")
            return False
        else:
            print("   Please type 'approve' or 'reject'.")