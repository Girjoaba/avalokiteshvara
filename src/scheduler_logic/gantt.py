"""Gantt chart generation — returns PNG bytes suitable for Telegram."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

import matplotlib
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from src.shared.models import ScheduleEntry

from .constants import DAY_END_HOUR, DAY_START_HOUR, PHASE_COLORS, PHASES_ORDER


def _split_working_segments(
    start_dt: datetime, end_dt: datetime,
) -> list[tuple[datetime, datetime]]:
    """Split a phase span into drawable segments within 08:00-16:00."""
    segments: list[tuple[datetime, datetime]] = []
    cursor = start_dt
    while cursor < end_dt:
        day_end = cursor.replace(
            hour=DAY_END_HOUR, minute=0, second=0, microsecond=0,
        )
        if end_dt <= day_end:
            segments.append((cursor, end_dt))
            break
        else:
            segments.append((cursor, day_end))
            cursor = (cursor + timedelta(days=1)).replace(
                hour=DAY_START_HOUR, minute=0, second=0, microsecond=0,
            )
    return segments


def generate_gantt_image(
    entries: list[ScheduleEntry],
    now: datetime | None = None,
) -> bytes:
    """Render a Gantt chart and return raw PNG bytes."""
    if not entries:
        return b""

    fig, ax = plt.subplots(figsize=(22, max(6, len(entries) * 0.85)))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")
    ax.tick_params(colors="#8b949e", labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")

    for i, entry in enumerate(entries):
        alpha = 0.45 if entry.is_existing else 0.88
        bar_end = entry.planned_end
        for phase in entry.production_order.phases:
            if not phase.starts_at or not phase.ends_at:
                continue
            if phase.ends_at > bar_end:
                bar_end = phase.ends_at
            color = PHASE_COLORS.get(phase.name, "#3498db")
            for seg_s, seg_e in _split_working_segments(phase.starts_at, phase.ends_at):
                ps = mdates.date2num(seg_s)
                pe = mdates.date2num(seg_e)
                ax.barh(
                    i, pe - ps, left=ps, height=0.62,
                    color=color, alpha=alpha,
                    edgecolor="#0d1117", linewidth=0.4,
                )

        dl = mdates.date2num(entry.deadline)
        ax.plot(
            dl, i, marker="D", color="#ffd700", markersize=8,
            zorder=5, markeredgecolor="#0d1117", markeredgewidth=0.8,
        )

        label_x = max(mdates.date2num(bar_end), dl)
        tag = "  (existing)" if entry.is_existing else ""
        slack_str = f"{'+' if entry.slack_hours >= 0 else ''}{entry.slack_hours:.1f}h"
        ax.text(
            label_x + 0.06, i,
            f"  {entry.sales_order.line.product_internal_id}"
            f" x{entry.sales_order.line.quantity}"
            f"  |  {entry.sales_order.internal_id.split('/')[-1]}"
            f"  |  {entry.sales_order.customer.name[:14]}"
            f"  |  P{entry.sales_order.priority}"
            f"  |  {slack_str} slack"
            f"{tag}",
            va="center", ha="left", fontsize=7.8,
            color="#c9d1d9", fontfamily="monospace",
        )

    now_num = mdates.date2num(now or datetime.now(timezone.utc))
    ax.axvline(
        now_num, color="#58a6ff", linewidth=2,
        linestyle="--", zorder=10, alpha=0.85, label="Now",
    )

    ax.set_yticks(range(len(entries)))
    ax.set_yticklabels(
        [f"{i + 1:02d}" for i in range(len(entries))],
        color="#58a6ff", fontsize=9, fontweight="bold",
    )

    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", color="#8b949e")

    all_starts = [e.planned_start for e in entries]
    all_ends = [e.planned_end for e in entries] + [e.deadline for e in entries]
    for e in entries:
        for ph in e.production_order.phases:
            if ph.ends_at:
                all_ends.append(ph.ends_at)
    earliest = min(all_starts)
    latest = max(all_ends)
    ax.set_xlim(
        mdates.date2num(earliest - timedelta(hours=8)),
        mdates.date2num(latest + timedelta(days=2)),
    )

    ax.invert_yaxis()
    ax.xaxis.grid(True, color="#21262d", linewidth=0.7)
    ax.yaxis.grid(False)
    ax.set_axisbelow(True)

    legend_els = [
        mpatches.Patch(facecolor=PHASE_COLORS[p], label=p, alpha=0.88)
        for p in PHASES_ORDER
    ]
    legend_els.append(plt.Line2D(
        [0], [0], color="#ffd700", marker="D", linestyle="None",
        markersize=7, label="Deadline",
    ))
    legend_els.append(plt.Line2D(
        [0], [0], color="#58a6ff", linestyle="--", label="Now",
    ))
    ax.legend(
        handles=legend_els, loc="lower right", fontsize=8,
        facecolor="#21262d", edgecolor="#30363d", labelcolor="#c9d1d9",
        ncol=3, framealpha=0.9,
    )

    on_time = sum(1 for e in entries if e.on_time)
    total = len(entries)
    status = "On Time" if on_time == total else f"{on_time}/{total} On Time"
    ax.set_title(
        f"NovaBoard — Production Schedule (EDF)  ·  {status}",
        fontsize=13, fontweight="bold", color="#c9d1d9", pad=12,
    )
    ax.set_xlabel("Date", color="#8b949e", fontsize=10)
    ax.set_ylabel("Order #", color="#8b949e", fontsize=10)

    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
