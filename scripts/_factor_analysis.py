"""
因子分析 + ML 模型训练 + 回测对比

流程:
  1. 加载最近 300 个交易日数据
  2. 批量计算 28 个技术因子（全向量化，快）
  3. 逐因子 IC 测试
  4. 训练 GradientBoosting 模型
  5. 回测对比 ML 评分 vs 按成交额选股
  6. 保存模型
"""
import sys, time, pickle
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import numpy as np
import pandas as pd
from config import DB_PATH
from core.factors import compute_factors, FACTOR_COLS, FACTOR_DESC

from sklearn.experimental import enable_hist_gradient_boosting
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
import warnings
warnings.filterwarnings("ignore")

TOP_N = 3
HOLD = 3
MIN_CLOSE = 5
MAX_CLOSE = 200
STOCKS_PER_DAY = 100

print("=" * 60)
print("  因子分析与 ML 模型训练")
print("=" * 60)

# ================================================================
# 1. 加载数据 — 只取近 300 交易日
# ================================================================
print("\n[1] 加载数据 (最近 300 交易日)...")
t0 = time.time()
conn = sqlite3.connect(str(DB_PATH))

# 取最近 300 个交易日的起始日期
date_ranges = conn.execute(
    "SELECT DISTINCT trade_date FROM market_snapshot ORDER BY trade_date DESC LIMIT 300"
).fetchall()
trade_dates = sorted([r[0] for r in date_ranges])
start_date = trade_dates[0]
end_date = trade_dates[-1]
print(f"  日期范围: {start_date} ~ {end_date} ({len(trade_dates)} 天)")

raw = pd.read_sql(
    """SELECT code, trade_date, name, sector,
              open, high, low, close, volume, amount,
              pct_chg, turnover_rate, volume_ratio, amplitude
       FROM market_snapshot
       WHERE trade_date >= ? AND trade_date <= ?
       ORDER BY code, trade_date""",
    conn, params=(start_date, end_date), parse_dates=["trade_date"],
)
conn.close()
print(f"  加载 {len(raw)} 行, {raw['code'].nunique()} 只股票 ({time.time()-t0:.0f}s)")

# ================================================================
# 2. 计算因子
# ================================================================
print("\n[2] 计算 28 个技术因子...")
t0 = time.time()
df = compute_factors(raw)
print(f"  完成 ({time.time()-t0:.0f}s)")

# ================================================================
# 3. IC 测试
# ================================================================
print("\n[3] 因子 IC 测试 (Spearman 秩相关: 因子 vs 3日收益)")
print("-" * 70)
t0 = time.time()

# 过滤: 活跃股 + 未来收益不能为空
mask = (
    df["close"].between(MIN_CLOSE, MAX_CLOSE)
    & ~df["name"].str.contains("ST|退", na=False)
    & df["fwd_return_3d"].notna()
)
valid = df[mask].copy()
valid.sort_values(["trade_date", "code"], inplace=True)

dates = valid["trade_date"].unique()
# 只保留因子列
factor_vals = {f: [] for f in FACTOR_COLS}

for d in dates:
    day = valid[valid["trade_date"] == d]
    fut = day["fwd_return_3d"].values
    for f in FACTOR_COLS:
        vals = day[f].values
        m = ~(np.isnan(vals) | np.isnan(fut))
        if m.sum() < 20:
            factor_vals[f].append(None)
            continue
        f_clip = np.clip(vals[m], np.percentile(vals[m], 1), np.percentile(vals[m], 99))
        r_clip = np.clip(fut[m], np.percentile(fut[m], 1), np.percentile(fut[m], 99))
        ic, _ = spearmanr(f_clip, r_clip)
        factor_vals[f].append(ic if not np.isnan(ic) else None)

ic_results = []
for f in FACTOR_COLS:
    ics = [v for v in factor_vals[f] if v is not None]
    if len(ics) < 10:
        continue
    mean_ic = np.mean(ics)
    std_ic = np.std(ics)
    ir = mean_ic / std_ic if std_ic > 0 else 0
    pos_ratio = np.mean([v > 0 for v in ics])
    ic_results.append({
        "factor": f, "desc": FACTOR_DESC.get(f, ""),
        "mean_ic": mean_ic, "ir": ir,
        "pos_ratio": pos_ratio, "days": len(ics),
    })

# 过滤掉数据天数太少的因子（f_amplitude 可能只有几天数据）
ic_results = [r for r in ic_results if r["days"] > 50]
ic_results.sort(key=lambda x: abs(x["mean_ic"]), reverse=True)
print(f"  {'因子':20s} {'IC均值':>8s} {'方向':>4s} {'IR':>8s} {'天数':>6s}")
print("  " + "-" * 55)
for r_ in ic_results:
    dir_ = "+" if r_["mean_ic"] > 0 else "-"
    flag = " <--" if abs(r_["mean_ic"]) > 0.02 else ""
    print(f"  {r_['factor']:20s} {r_['mean_ic']:8.4f} {dir_:>4s} {r_['ir']:8.3f} {r_['days']:6d}{flag}")

print(f"  ({time.time()-t0:.0f}s)")

# 选出 IC 显著因子
selected = [r["factor"] for r in ic_results if abs(r["mean_ic"]) > 0.01]
if len(selected) < 3:
    selected = FACTOR_COLS  # fallback
print(f"\n  选入 ML 模型: {len(selected)} 个因子")

# ================================================================
# 4. 时间序列划分
# ================================================================
print(f"\n[4] 时间序列划分 (60% 训练 / 20% 验证 / 20% 测试)...")
all_dates = sorted(valid["trade_date"].unique())
n = len(all_dates)
train_end = int(n * 0.60)
val_end = int(n * 0.80)

train_dates = set(all_dates[:train_end])
val_dates = set(all_dates[train_end:val_end])
test_dates = set(all_dates[val_end:])

print(f"  训练: {all_dates[0].date()} ~ {all_dates[train_end-1].date()} ({len(train_dates)}天)")
print(f"  验证: {all_dates[train_end].date()} ~ {all_dates[val_end-1].date()} ({len(val_dates)}天)")
print(f"  测试: {all_dates[val_end].date()} ~ {all_dates[-1].date()} ({len(test_dates)}天)")

# ================================================================
# 5. 训练 ML 模型
# ================================================================
print(f"\n[5] 训练 GradientBoosting 模型...")
t0 = time.time()

train = valid[valid["trade_date"].isin(train_dates)]
val = valid[valid["trade_date"].isin(val_dates)]

X_train = train[selected].values
y_train = train["target_3d"].values
X_val = val[selected].values
y_val = val["target_3d"].values

# 将 inf 转为 NaN，再以中位数填充
X_train = np.where(np.isfinite(X_train), X_train, np.nan)
X_val = np.where(np.isfinite(X_val), X_val, np.nan)
from sklearn.impute import SimpleImputer
imputer = SimpleImputer(strategy="median")
X_train = imputer.fit_transform(X_train)
X_val = imputer.transform(X_val)

# 极端值截断（防止除零异常值干扰模型）
X_train = np.clip(X_train, -100, 100)
X_val = np.clip(X_val, -100, 100)

print(f"  训练: {X_train.shape[0]} 样本 (正向 {y_train.mean():.1%})")

model = HistGradientBoostingClassifier(
    max_iter=200, max_depth=4,
    learning_rate=0.05, random_state=42,
)
model.fit(X_train, y_train)

val_prob = model.predict_proba(X_val)[:, 1]
val_auc = roc_auc_score(y_val, val_prob)
print(f"  验证 AUC: {val_auc:.4f}  ({time.time()-t0:.0f}s)")

print(f"  (HistGBM 不直接输出特征重要性)")

# ================================================================
# 6. 回测对比
# ================================================================
print(f"\n[6] 回测对比 (每日选 TOP {TOP_N}, HOLD {HOLD} 天)")
print("-" * 60)
t0 = time.time()

test = valid[valid["trade_date"].isin(test_dates)].copy()
test_dates_sorted = sorted(test_dates)

ml_trades, bench_trades = [], []

for td in test_dates_sorted:
    day = test[test["trade_date"] == td]
    if len(day) < 10:
        continue
    # 取成交额前 STOCKS_PER_DAY
    day = day.nlargest(STOCKS_PER_DAY, "amount")
    if len(day) < TOP_N:
        continue

    # ML 评分（inf→nan→中位数填充→截断）
    feat = imputer.transform(np.where(np.isfinite(day[selected].values), day[selected].values, np.nan))
    feat = np.clip(feat, -100, 100)
    scores = model.predict_proba(feat)[:, 1]
    day = day.copy()
    day["ml_score"] = scores

    for _, s in day.nlargest(TOP_N, "ml_score").iterrows():
        ml_trades.append(s["fwd_return_3d"])
    for _, s in day.nlargest(TOP_N, "amount").iterrows():
        bench_trades.append(s["fwd_return_3d"])


def show(label, rets):
    if not rets:
        print(f"\n  {label}: 无交易")
        return
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n = len(rets)
    print(f"\n  {label}:")
    print(f"    交易: {n}  |  胜率: {len(wins)/n:.1%} ({len(wins)}/{n})")
    print(f"    平均: {np.mean(rets):+.2%}  |  累计: {sum(rets):+.2%}")
    if wins:
        print(f"    平均赢: {np.mean(wins):+.2%}  |  平均亏: {np.mean(losses):+.2%}" if losses else "")

show("ML 模型", ml_trades)
show("成交额选股(基准)", bench_trades)
print(f"\n  ({time.time()-t0:.0f}s)")

# ================================================================
# 7. 保存模型
# ================================================================
model_dir = Path(__file__).resolve().parent.parent / "saved_models"
model_dir.mkdir(exist_ok=True)
with open(model_dir / "ml_scorer.pkl", "wb") as f:
    pickle.dump({"model": model, "imputer": imputer, "selected_factors": selected}, f)
with open(model_dir / "selected_factors.txt", "w") as f:
    for fac in selected:
        f.write(f"{fac}\n")

print(f"\n  模型已保存: {model_dir / 'ml_scorer.pkl'}")
print(f"  特征列表:  {model_dir / 'selected_factors.txt'}")

# ================================================================
# 总结
# ================================================================
print("\n" + "=" * 60)
print("  总结")
print("=" * 60)
print(f"  有效因子 (|IC|>0.02):")
for r_ in ic_results:
    if abs(r_["mean_ic"]) > 0.02:
        print(f"    {r_['factor']:20s} IC={r_['mean_ic']:+.4f}  IR={r_['ir']:.2f}")
print(f"\n  ML AUC: {val_auc:.4f}")
if ml_trades and bench_trades:
    ml_wr = np.mean([r > 0 for r in ml_trades])
    bw_wr = np.mean([r > 0 for r in bench_trades])
    print(f"  ML 胜率: {ml_wr:.1%} ({len(ml_trades)}次)  vs  基准胜率: {bw_wr:.1%} ({len(bench_trades)}次)")
