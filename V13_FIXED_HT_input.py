
import pandas as pd
import glob

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

def main():

    print("\n=== V13 DATA + LIVE EDGE BOT ===")

    league = input("League: ")
    ex_sc = input("Predicted score: ")
    exp_h, exp_a = parse_ex_sc(ex_sc)
    fav = "home" if exp_h > exp_a else "away"
    goal_diff = abs(exp_h - exp_a)

    minute = int(input("Minute: "))
    score = input("Current score (0-0): ")

    h, a = map(int, score.split("-"))
    current_total = h + a

    data, source = smart_filter(df, league, ex_sc)

    if len(data) < 30:
        print("❌ Not enough data")
        return

    # =========================
    # HT INPUT ONLY IF NEEDED
    # =========================
    if minute >= 46:
        ht_score = input("HT score (0-0): ")
        ht_h, ht_a = map(int, ht_score.split("-"))

        ht_probs = get_ht_probs(data, ht_h, ht_a)

        if ht_probs:
            probs = ht_probs
            print("📊 Using HT-based data")
            print(f"Using HT: {ht_h}-{ht_a}")
        else:
            probs = get_probs(data)
            print("⚠️ HT sample too small → using FT data")
    else:
        probs = get_probs(data)

    # =========================
    # PURE DATA OUTPUT
    # =========================
    raw_probs = probs.copy()

    print("\n=== PURE DATA ===")
    for k,v in raw_probs.items():
        print(f"{k}: {v*100:.2f}% (fair {1/v:.2f})")

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

    print("\n=== LIVE MODEL ===")
    for k,v in adjusted.items():
        print(f"{k}: {v*100:.2f}% (fair {1/v:.2f})")

    # =========================
    # EDGE DETECTION
    # =========================
    print("\n=== EDGE (MODEL - DATA) ===")
    for k in adjusted:
        edge = adjusted[k] - raw_probs[k]
        print(f"{k}: {edge*100:.2f}%")

if __name__ == "__main__":
    main()
