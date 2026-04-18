import pandas as pd
import glob
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# =========================
# LOAD DATA (TĀPAT KĀ TEV)
# =========================
files = glob.glob("data/*.xlsx")
df = pd.concat([pd.read_excel(f) for f in files], ignore_index=True)

def parse_ex_sc(ex_sc):
    try:
        h, a = ex_sc.replace(" ","").split("-")
        return int(h), int(a)
    except:
        return 0,0

def parse_score(score):
    try:
        h, a = str(score).replace(" ","").split("-")
        return int(h), int(a)
    except:
        return None, None

def parse_ht(ht):
    try:
        ht = str(ht).replace("(", "").replace(")", "").replace(":", "-")
        h, a = ht.split("-")
        return int(h), int(a)
    except:
        return None, None

df[['home','away']] = df['l_scr'].apply(lambda x: pd.Series(parse_score(x)))
df[['ht_home','ht_away']] = df['ht_scr'].apply(lambda x: pd.Series(parse_ht(x)))
df['total'] = df['home'] + df['away']

def smart_filter(df, league, ex_sc):
    league_df = df[df['shortTag'].str.lower() == league.lower()]
    ex_df = df[df['ex_sc'].str.replace(" ","") == ex_sc.replace(" ","")]

    both = league_df[
        league_df['ex_sc'].str.replace(" ","") == ex_sc.replace(" ","")
    ]

    if len(both) >= 50:
        return both, "LEAGUE + EX_SC"
    if len(league_df) >= 100:
        return league_df, "LEAGUE ONLY"
    if len(ex_df) >= 100:
        return ex_df, "EX_SC ONLY"

    return df, "GLOBAL"

def get_probs(data):
    total = data['total']
    btts = ((data['home'] > 0) & (data['away'] > 0))

    return {
        "Over 0.5": (total >= 1).mean(),
        "Over 1.5": (total >= 2).mean(),
        "Over 2.5": (total >= 3).mean(),
        "Over 3.5": (total >= 4).mean(),
        "BTTS YES": btts.mean(),
        "BTTS NO": 1 - btts.mean()
    }

def get_ht_probs(data, h, a):
    subset = data[
        (data['ht_home'] == h) &
        (data['ht_away'] == a)
    ]

    if len(subset) < 1:
        return None

    total = subset['total']
    btts = ((subset['home'] > 0) & (subset['away'] > 0))

    return {
        "Over 0.5": (total >= 1).mean(),
        "Over 1.5": (total >= 2).mean(),
        "Over 2.5": (total >= 3).mean(),
        "Over 3.5": (total >= 4).mean(),
        "BTTS YES": btts.mean(),
        "BTTS NO": 1 - btts.mean()
    }

# =========================
# TELEGRAM HANDLER
# =========================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()

        # FORMAT:
        # EPL 2-1 65 1-0
        # vai:
        # EPL 2-1 70 1-0 HT:1-0

        parts = text.split()

        league = parts[0]
        ex_sc = parts[1]
        minute = int(parts[2])
        score = parts[3]

        h, a = map(int, score.split("-"))
        current_total = h + a

        exp_h, exp_a = parse_ex_sc(ex_sc)
        goal_diff = abs(exp_h - exp_a)

        data, source = smart_filter(df, league, ex_sc)

        if len(data) < 30:
            await update.message.reply_text("❌ Not enough data")
            return

        # =========================
        # HT LOGIC
        # =========================
        if minute >= 46 and len(parts) >= 5:
            ht_score = parts[4].replace("HT:", "")
            ht_h, ht_a = map(int, ht_score.split("-"))

            ht_probs = get_ht_probs(data, ht_h, ht_a)

            if ht_probs:
                probs = ht_probs
                mode = f"HT ({ht_h}-{ht_a})"
            else:
                probs = get_probs(data)
                mode = "FT fallback"
        else:
            probs = get_probs(data)
            mode = "FT"

        raw_probs = probs.copy()

        # =========================
        # LIVE MODEL
        # =========================
        adjusted = {}
        btts_yes_value = None

        for k, v in probs.items():

            if "Over" in k:
                base = v

                if k == "Over 0.5":
                    needed = 1 - current_total
                elif k == "Over 1.5":
                    needed = 2 - current_total
                elif k == "Over 2.5":
                    needed = 3 - current_total
                elif k == "Over 3.5":
                    needed = 4 - current_total

                if needed <= 0:
                    adj = 0.99
                else:
                    if minute > 60:
                        base *= 0.85
                    elif minute > 30:
                        base *= 0.93

                    if current_total > 0:
                        base *= 1.05

                    if needed >= 2:
                        base *= 0.85
                    if needed >= 3:
                        base *= 0.7

                    adj = max(0.02, min(0.95, base))

            elif k == "BTTS YES":
                base = v

                if h == 0 or a == 0:
                    base *= 0.85

                if goal_diff >= 3:
                    base *= 0.8

                if minute > 60:
                    base *= 0.8

                adj = max(0.02, min(0.95, base))
                btts_yes_value = adj

            elif k == "BTTS NO":
                if btts_yes_value is not None:
                    adj = 1 - btts_yes_value
                else:
                    adj = v

            adjusted[k] = adj

        if "BTTS YES" in adjusted:
            adjusted["BTTS NO"] = 1 - adjusted["BTTS YES"]

        # =========================
        # OUTPUT
        # =========================
        msg = f"⚽ {league} | {ex_sc} | {minute}' | {score}\n"
        msg += f"📊 Mode: {mode} ({source})\n\n"

        msg += "=== DATA ===\n"
        for k,v in raw_probs.items():
            msg += f"{k}: {v*100:.1f}%\n"

        msg += "\n=== LIVE ===\n"
        for k,v in adjusted.items():
            msg += f"{k}: {v*100:.1f}%\n"

        msg += "\n=== EDGE ===\n"
        for k in adjusted:
            edge = adjusted[k] - raw_probs[k]
            msg += f"{k}: {edge*100:.1f}%\n"

        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(
            "❌ Format error\n\nExample:\nEPL 2-1 65 1-0\nEPL 2-1 70 1-0 HT:1-0"
        )

# =========================
# RUN
# =========================
app = ApplicationBuilder().token("8733388578:AAFaPueO8D1n9b4FD4TFuPArY5CqNyazMgs").build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

app.run_polling()