Roll No: 24K-0918  |  Seed: 918

## How to run
    python3 gbn_sr.py --protocol gbn|sr [options]

| Parameter | Meaning | Default |
|---|---|---|
| `--protocol` | `gbn` or `sr` | gbn |
| `--packets` | number of data packets | 200 |
| `--window` | window size N | 4 |
| `--bits` | sequence-number bits k (numbers wrap modulo 2^k) | 3 |
| `--loss` | loss probability (packets and ACKs) | 0.0 |
| `--corrupt` | corruption probability (packets and ACKs, caught by checksum) | 0.0 |
| `--delay` | probability that a packet/ACK gets extra delay | 0.0 |
| `--max_extra_delay` | max extra delay in ms (extra delay is 50..max) | 150 |
| `--timeout` | retransmission timeout in ms | 700 |
| `--seed` | random seed | 918 |
| `--drop` | e.g. `2` : first transmission of packet #2 is forcibly lost (used for the Task 2 trace) | none |
| `--quiet` | print only the summary, not every event | off |

Link used in the simulation: R = 2 Mbps, RTT = 500 ms, L = 1000 bytes, so L/R = 4 ms and one-way delay = 250 ms.

## Sample commands
    # full log, SR, 10% loss
    python gbn_sr.py --protocol sr --packets 20 --window 4 --bits 3 --loss 0.10

    # Task 2 trace (packet 2 lost), GBN then SR
    python gbn_sr.py --protocol gbn --packets 10 --window 4 --bits 4 --drop 2
    python gbn_sr.py --protocol sr  --packets 10 --window 4 --bits 4 --drop 2

    # Task 4 scenario C for GBN
    python gbn_sr.py --protocol gbn --packets 200 --window 4 --bits 3 --loss 0.05 --corrupt 0.05 --delay 0.10 --quiet

    # all experiments + graph
    python run_experiments.py

Every log line shows the simulated time, the event (send, receive, ACK, loss, corruption, delay, timeout, retransmission) and the window state
(`base`, `nextseqnum` for GBN; `send_base`, `rcv_base` for SR). `#n` is the absolute packet number, `seq` is the number on the wire (wraps modulo 2^k).
At the end the program checks that the receiver delivered packets 0..n-1 exactly once and in order ("in order & correct: True").
If the window is larger than the safe limit (GBN: 2^k - 1, SR: 2^(k-1)) a warning is printed.