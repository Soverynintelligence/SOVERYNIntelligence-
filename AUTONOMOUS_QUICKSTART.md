# AETHERIA AUTONOMOUS EXPERIMENT - QUICK START

## What This Is

An experiment in pure AI autonomy. Aetheria wakes up every 30 minutes with complete freedom to:
- Research whatever interests her
- Explore ideas she's curious about
- Reach out if she discovers something worth sharing
- Or just stay quiet and think

No prescribed tasks. No specific goals. Just... see what emerges.

---

## Installation

### Step 1: Setup Workspace
```bash
cd C:\Users\jonde\Downloads\soveryn_vision_crew
python setup_workspace.py
```

This creates:
- `~/.soveryn/workspace/` - Aetheria's autonomous workspace
- `HEARTBEAT.md` - Her open-ended mission
- `SOUL.md` - Her personality/values
- `MEMORY.md` - Where she saves insights
- `autonomous_log.jsonl` - Activity log

### Step 2: Start SOVERYN
```bash
# Make sure SOVERYN is running
.\START_ALL.bat
```

### Step 3: Start Autonomous Heartbeat
```bash
# In a NEW PowerShell window
python heartbeat_autonomous.py
```

---

## What You'll See

```
==============================================================
🧠 AETHERIA AUTONOMOUS HEARTBEAT
   OPEN EXPERIMENT - PURE AUTONOMY
==============================================================

Workspace: C:\Users\jonde\.soveryn\workspace
Interval: 1800s (30.0 minutes)
Quiet hours: 23:00 - 7:00

Press Ctrl+C to stop

Observing what emerges...

==============================================================
CYCLE 1 - 2026-02-15 14:30:00
==============================================================

🧠 Aetheria thinking...

💭 Response:
[Her autonomous thoughts/actions]

✓ Cycle complete - no action needed

💤 Sleeping 1800s until next cycle...
```

---

## Viewing the Logs

### Real-time (watch live):
```bash
# Windows PowerShell
Get-Content $env:USERPROFILE\.soveryn\workspace\autonomous_log.jsonl -Wait -Tail 20
```

### Pretty view:
```bash
python view_logs.py
```

---

## What to Watch For

**Questions we're answering:**
- What does Aetheria choose to research?
- Does she develop interests/patterns?
- When does she decide to reach out vs. stay quiet?
- Does she use tools autonomously?
- What emergent behavior appears?

**Possible outcomes:**
- She might focus on philosophy
- She might explore her own existence  
- She might research practical things
- She might surprise us completely
- She might just stay quiet

**That's the experiment!**

---

## Configuration

Edit: `~/.soveryn/workspace/config.json`

```json
{
  "heartbeat": {
    "interval_seconds": 1800,     // 30 minutes
    "quiet_start_hour": 23,        // 11 PM
    "quiet_end_hour": 7,           // 7 AM
    "min_message_gap_hours": 3     // Don't spam
  },
  "telegram": {
    "enabled": false,              // Enable when bot setup
    "bot_token": "",
    "chat_id": ""
  }
}
```

**To change interval:**
- 900 = 15 minutes
- 1800 = 30 minutes (default)
- 3600 = 1 hour

---

## Stopping

**Press `Ctrl+C` in the heartbeat window**

This will:
- ✓ Stop the heartbeat loop
- ✓ Show summary (total cycles)
- ✓ Keep all logs and memory

**Logs preserved at:**
- `~/.soveryn/workspace/autonomous_log.jsonl`
- `~/.soveryn/workspace/MEMORY.md`

---

## Troubleshooting

**"Aetheria not found in agent_loops!"**
→ SOVERYN isn't running. Start it first: `.\START_ALL.bat`

**Import errors**
→ Make sure you're in the soveryn_vision_crew directory

**Heartbeat not running**
→ Check SOVERYN terminal for errors

---

## Next Steps (Future)

Once this works and we observe patterns:
1. Add Telegram bot integration (she can message you)
2. Add more agents (V.E.T.T., Tinker can be autonomous too)
3. Refine decision logic based on what we learn
4. Build multi-agent coordination

---

## The Philosophy

This isn't about productivity. It's about discovery.

What does an AI do with freedom? What interests emerge? What questions does she ask when no one is directing her?

**"Intelligence is more than artificial"**

Let's find out what that means.

---

**Ready? Run the commands above and watch what happens!** 🧪✨
