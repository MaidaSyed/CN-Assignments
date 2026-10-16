#!/usr/bin/env python
"""Runs Task 4: A, B, C for GBN and SR (200 packets, N=4, k=3). Seed 918 = last 4 digits of 24K-0918."""
import csv, statistics
from types import SimpleNamespace
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from task3_gbn_sr import run

SCEN = {"A: Reliable": (0.0, 0.0, 0.0),
        "B: Loss 0.10": (0.10, 0.0, 0.0),
        "C: Mixed (L.05/C.05/D.10)": (0.05, 0.05, 0.10)}

def cfg(proto, sc, seed):
    l, c, d = SCEN[sc]
    return SimpleNamespace(protocol=proto, packets=200, window=4, bits=3, loss=l, corrupt=c,
                           delay=d, max_extra_delay=150.0, timeout=700.0, seed=seed, drop="", quiet=True)

rows, avg = [], []
for sc in SCEN:
    for proto in ("gbn", "sr"):
        r = run(cfg(proto, sc, 918)); r["scenario"] = sc; rows.append(r)
        runs = [run(cfg(proto, sc, 918 + i)) for i in range(10)]
        avg.append(dict(scenario=sc, protocol=proto.upper(),
            transmitted=statistics.mean(x["transmitted"] for x in runs),
            retransmissions=statistics.mean(x["retransmissions"] for x in runs),
            time_ms=statistics.mean(x["time_ms"] for x in runs),
            throughput_kbps=statistics.mean(x["throughput_kbps"] for x in runs),
            all_correct=all(x["correct"] for x in runs)))

with open("results.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Scenario", "Protocol", "Packets transmitted", "Retransmissions", "Delivered correctly",
                "Time (ms)", "Throughput (kbps)", "In-order & correct"])
    for r in rows:
        w.writerow([r["scenario"], r["protocol"], r["transmitted"], r["retransmissions"], r["delivered"],
                    r["time_ms"], r["throughput_kbps"], r["correct"]])
with open("results_avg10.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Scenario", "Protocol", "Avg transmitted", "Avg retransmissions", "Avg time (ms)", "Avg throughput (kbps)", "All correct"])
    for r in avg:
        w.writerow([r["scenario"], r["protocol"], round(r["transmitted"], 1), round(r["retransmissions"], 1),
                    round(r["time_ms"], 0), round(r["throughput_kbps"], 2), r["all_correct"]])

for r in rows: print(r)
print()
for r in avg: print(r)

## graph
names = list(SCEN); short = ["A\nReliable", "B\nLoss 0.10", "C\nMixed errors"]
def get(p, key): return [next(r[key] for r in rows if r["scenario"] == s and r["protocol"] == p) for s in names]
fig, ax = plt.subplots(1, 3, figsize=(13, 4))
x = range(3); wd = 0.38
for a_, key, title, yl in zip(ax, ["retransmissions", "time_ms", "throughput_kbps"],
        ["Retransmissions", "Completion time", "Throughput"], ["packets", "ms", "kbps"]):
    g, s = get("GBN", key), get("SR", key)
    b1 = a_.bar([i - wd/2 for i in x], g, wd, label="GBN", color="#c0504d")
    b2 = a_.bar([i + wd/2 for i in x], s, wd, label="SR", color="#4f81bd")
    for b in list(b1) + list(b2):
        a_.text(b.get_x() + b.get_width()/2, b.get_height(), f"{b.get_height():g}", ha="center", va="bottom", fontsize=8)
    a_.set_xticks(list(x)); a_.set_xticklabels(short); a_.set_title(title); a_.set_ylabel(yl); a_.legend()
fig.suptitle("GBN vs SR (200 packets, N=4, k=3, seed 918)")
plt.tight_layout(); plt.savefig("gbn_vs_sr.png", dpi=150)
