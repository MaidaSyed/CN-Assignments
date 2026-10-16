import argparse
import heapq
import random
from collections import deque

# ---------------- link constants (from the scenario) ----------------
LINK_RATE = 2_000_000          # bits per second
PKT_BITS = 8000                # L = 1000 bytes
RTT_MS = 500.0
TX_MS = PKT_BITS / LINK_RATE * 1000.0   # 4 ms
OWD_MS = RTT_MS / 2.0                   # 250 ms one way

DATA, ACK = "DATA", "ACK"

# ---------------- packets and checksum ----------------
def checksum(kind, seq, payload):
    data = bytes([0 if kind == DATA else 1]) + seq.to_bytes(2, "big") + payload
    if len(data) % 2:
        data += b"\x00"
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def make_packet(kind, seq, payload, idx=None):
    # idx is only used for logging / forced loss, never by the protocol logic
    return {"kind": kind, "seq": seq, "payload": payload,
            "csum": checksum(kind, seq, payload), "idx": idx}

def verify(pkt):
    return pkt["csum"] == checksum(pkt["kind"], pkt["seq"], pkt["payload"])

def make_payload(idx):
    return idx.to_bytes(4, "big") + b"RESCUE-DATA"

# ---------------- simulator core ----------------
class Sim:
    def __init__(self, a):
        self.a = a
        self.t = 0.0
        self.q = []
        self.cnt = 0
        self.rng = random.Random(a.seed)
        self.force = set(int(x) for x in a.drop.split(",") if x.strip() != "")
        self.forced_done = set()
        self.stats = dict(tx=0, rtx=0, acks=0, lost_data=0, lost_ack=0,
                          corrupt_data=0, corrupt_ack=0, delayed=0, timeouts=0)

    def schedule(self, t, kind, target, *args):
        heapq.heappush(self.q, (t, self.cnt, kind, target, args))
        self.cnt += 1

    def log(self, msg):
        if not self.a.quiet:
            print(f"[{self.t:9.2f} ms] {msg}")

    def channel_send(self, pkt, dest_kind, dest):
        """The unreliable channel: loss, corruption, delay."""
        a = self.a
        tag = f"{pkt['kind']}{pkt['seq']}"
        key = "data" if pkt["kind"] == DATA else "ack"
        forced = (pkt["kind"] == DATA and pkt["idx"] in self.force
                  and pkt["idx"] not in self.forced_done)
        if forced:
            self.forced_done.add(pkt["idx"])
        if forced or self.rng.random() < a.loss:
            self.stats["lost_" + key] += 1
            self.log(f"  CHANNEL  {tag} LOST")
            return
        pkt = dict(pkt)
        if self.rng.random() < a.corrupt:
            self.stats["corrupt_" + key] += 1
            if pkt["kind"] == DATA:
                b = bytearray(pkt["payload"])
                b[self.rng.randrange(len(b))] ^= 1 << self.rng.randrange(8)
                pkt["payload"] = bytes(b)
            else:
                pkt["seq"] ^= 1 << self.rng.randrange(max(1, a.bits))
            self.log(f"  CHANNEL  {tag} CORRUPTED")
        extra = 0.0
        if self.rng.random() < a.delay:
            extra = self.rng.uniform(50.0, a.max_extra_delay)
            self.stats["delayed"] += 1
            self.log(f"  CHANNEL  {tag} DELAYED by {extra:.0f} ms")
        self.schedule(self.t + OWD_MS + extra, dest_kind, dest, pkt)

# ---------------- sender base ----------------
class SenderBase:
    def __init__(self, sim):
        self.sim = sim
        a = sim.a
        self.n = a.packets
        self.N = a.window
        self.M = 2 ** a.bits
        self.base = 0          # oldest unACKed packet (send_base for SR)
        self.next = 0          # nextseqnum
        self.link_free = 0.0
        self.send_pending = False
        self.rtx = deque()
        self.receiver = None

    def done(self):
        return self.base >= self.n

    def can_send_new(self):
        return self.next < self.n and self.next < self.base + self.N

    def pump(self):
        if self.send_pending:
            return
        if self.rtx or self.can_send_new():
            self.send_pending = True
            self.sim.schedule(max(self.sim.t, self.link_free), "send", self)

    def on_send_event(self):
        self.send_pending = False
        while self.rtx:
            idx = self.rtx.popleft()
            if self.still_needed(idx):
                self.transmit(idx, True)
                break
        else:
            if self.can_send_new():
                idx = self.next
                self.next += 1
                self.transmit(idx, False)
        self.pump()

    def transmit(self, idx, is_rtx):
        sim = self.sim
        seq = idx % self.M
        pkt = make_packet(DATA, seq, make_payload(idx), idx)
        self.link_free = sim.t + TX_MS
        sim.stats["tx"] += 1
        if is_rtx:
            sim.stats["rtx"] += 1
        word = "RETRANSMIT" if is_rtx else "send"
        sim.log(f"SENDER   {word} pkt seq={seq} (#{idx})   {self.state()}")
        self.after_transmit(idx, is_rtx)
        sim.channel_send(pkt, "rx_data", self.receiver)

# ---------------- Go-Back-N ----------------
class GBNSender(SenderBase):
    def __init__(self, sim):
        super().__init__(sim)
        self.timer_ver = 0
        self.timer_on = False

    def state(self):
        return (f"[base=#{self.base} nextseqnum=#{self.next} "
                f"window=#{self.base}..#{self.base + self.N - 1}]")

    def still_needed(self, idx):
        return idx >= self.base

    def start_timer(self):          # ONE timer, for the oldest unACKed packet
        self.timer_ver += 1
        self.timer_on = True
        self.sim.schedule(self.sim.t + self.sim.a.timeout, "timeout",
                          self, self.timer_ver)

    def stop_timer(self):
        self.timer_ver += 1
        self.timer_on = False

    def after_transmit(self, idx, is_rtx):
        if idx == self.base and (is_rtx or not self.timer_on):
            self.start_timer()

    def on_ack(self, pkt):
        sim = self.sim
        if not verify(pkt):
            sim.log("SENDER   ACK corrupted -> ignored")
            return
        a = pkt["seq"]
        for idx in range(self.base, self.next):
            if idx % self.M == a:       # cumulative ACK: everything up to idx
                self.base = idx + 1
                sim.log(f"SENDER   cumulative ACK{a} -> base moves to #{self.base} "
                        f"{self.state()}")
                if self.base == self.next:
                    self.stop_timer()
                else:
                    self.start_timer()
                if self.done():
                    return
                self.pump()
                return
        sim.log(f"SENDER   duplicate/old ACK{a} -> ignored {self.state()}")

    def on_timeout(self, ver):
        if ver != self.timer_ver or not self.timer_on:
            return
        sim = self.sim
        self.timer_on = False
        sim.stats["timeouts"] += 1
        sim.log(f"SENDER   TIMEOUT -> go back, resend #{self.base}..#{self.next - 1}")
        self.rtx = deque(range(self.base, self.next))
        self.pump()

class GBNReceiver:
    def __init__(self, sim):
        self.sim = sim
        self.M = 2 ** sim.a.bits
        self.expectedseqnum = 0
        self.have_any = False
        self.delivered = []
        self.sender = None

    def send_ack(self, seq):
        sim = self.sim
        sim.stats["acks"] += 1
        sim.log(f"RECEIVER send ACK{seq}")
        sim.channel_send(make_packet(ACK, seq, b""), "rx_ack", self.sender)

    def on_data(self, pkt):
        sim = self.sim
        if not verify(pkt):
            sim.log("RECEIVER data corrupted (checksum) -> discarded")
            if self.have_any:
                self.send_ack((self.expectedseqnum - 1) % self.M)
            return
        seq = pkt["seq"]
        if seq == self.expectedseqnum:
            self.delivered.append(int.from_bytes(pkt["payload"][:4], "big"))
            sim.log(f"RECEIVER pkt{seq} in order -> delivered "
                    f"(expectedseqnum -> {(seq + 1) % self.M})")
            self.expectedseqnum = (self.expectedseqnum + 1) % self.M
            self.have_any = True
            self.send_ack(seq)
        else:
            sim.log(f"RECEIVER pkt{seq} out of order (expected "
                    f"{self.expectedseqnum}) -> discarded")
            if self.have_any:
                self.send_ack((self.expectedseqnum - 1) % self.M)

# ---------------- Selective Repeat ----------------
class SRSender(SenderBase):
    def __init__(self, sim):
        super().__init__(sim)
        self.acked = set()
        self.timer_ver = {}

    def state(self):
        return (f"[send_base=#{self.base} nextseqnum=#{self.next} "
                f"window=#{self.base}..#{self.base + self.N - 1}]")

    def still_needed(self, idx):
        return idx >= self.base and idx not in self.acked

    def after_transmit(self, idx, is_rtx):     # one timer per packet
        ver = self.timer_ver.get(idx, 0) + 1
        self.timer_ver[idx] = ver
        self.sim.schedule(self.sim.t + self.sim.a.timeout, "timeout",
                          self, idx, ver)

    def on_ack(self, pkt):
        sim = self.sim
        if not verify(pkt):
            sim.log("SENDER   ACK corrupted -> ignored")
            return
        a = pkt["seq"]
        found = False
        for idx in range(self.base, self.next):
            if idx % self.M == a:
                found = True
                if idx in self.acked:
                    sim.log(f"SENDER   duplicate ACK{a}")
                else:
                    self.acked.add(idx)
                    self.timer_ver[idx] = self.timer_ver.get(idx, 0) + 1
                    sim.log(f"SENDER   individual ACK{a} (#{idx}) marked acked")
                break
        if not found:
            sim.log(f"SENDER   old ACK{a} -> ignored")
        moved = False
        while self.base in self.acked:
            self.acked.discard(self.base)
            self.base += 1
            moved = True
        if moved:
            sim.log(f"SENDER   window slides {self.state()}")
        if self.done():
            return
        self.pump()

    def on_timeout(self, idx, ver):
        if idx < self.base or idx in self.acked or self.timer_ver.get(idx) != ver:
            return
        sim = self.sim
        sim.stats["timeouts"] += 1
        sim.log(f"SENDER   TIMEOUT for #{idx} -> resend only this packet")
        self.rtx.append(idx)
        self.pump()

class SRReceiver:
    def __init__(self, sim):
        self.sim = sim
        self.N = sim.a.window
        self.M = 2 ** sim.a.bits
        self.rcv_base = 0
        self.buf = {}
        self.delivered = []
        self.sender = None

    def send_ack(self, seq):
        sim = self.sim
        sim.stats["acks"] += 1
        sim.log(f"RECEIVER send ACK{seq}")
        sim.channel_send(make_packet(ACK, seq, b""), "rx_ack", self.sender)

    def on_data(self, pkt):
        sim = self.sim
        if not verify(pkt):
            sim.log("RECEIVER data corrupted (checksum) -> discarded, no ACK")
            return
        seq = pkt["seq"]
        if (seq - self.rcv_base) % self.M < self.N:       # inside rcv window
            self.send_ack(seq)
            if seq in self.buf:
                sim.log(f"RECEIVER pkt{seq} duplicate (already buffered)")
            elif seq != self.rcv_base:
                sim.log(f"RECEIVER pkt{seq} out of order -> buffered "
                        f"(rcv_base={self.rcv_base})")
                self.buf[seq] = pkt["payload"]
            else:
                self.buf[seq] = pkt["payload"]
            while self.rcv_base in self.buf:
                self.delivered.append(int.from_bytes(self.buf.pop(self.rcv_base)[:4], "big"))
                sim.log(f"RECEIVER delivered pkt{self.rcv_base} in order")
                self.rcv_base = (self.rcv_base + 1) % self.M
                sim.log(f"RECEIVER window moves, rcv_base={self.rcv_base}")
        elif 1 <= (self.rcv_base - seq) % self.M <= self.N:   # old packet
            sim.log(f"RECEIVER pkt{seq} old duplicate -> re-ACK")
            self.send_ack(seq)
        else:
            sim.log(f"RECEIVER pkt{seq} outside window -> ignored")


# ---------------- run one simulation ----------------
def run(a):
    sim = Sim(a)
    M = 2 ** a.bits
    limit = M - 1 if a.protocol == "gbn" else M // 2
    if a.window > limit:
        print(f"WARNING: window {a.window} > safe maximum {limit} for "
              f"{a.protocol.upper()} with {a.bits}-bit sequence numbers")
    if a.protocol == "gbn":
        snd, rcv = GBNSender(sim), GBNReceiver(sim)
    else:
        snd, rcv = SRSender(sim), SRReceiver(sim)
    snd.receiver, rcv.sender = rcv, snd
    snd.pump()
    events = 0
    while sim.q and not snd.done() and events < 5_000_000:
        events += 1
        t, _, kind, target, args = heapq.heappop(sim.q)
        sim.t = t
        if kind == "send":
            target.on_send_event()
        elif kind == "rx_data":
            target.on_data(*args)
        elif kind == "rx_ack":
            target.on_ack(*args)
        elif kind == "timeout":
            target.on_timeout(*args)
    finished = snd.done()
    elapsed = sim.t
    ok = finished and rcv.delivered == list(range(a.packets))
    thr = a.packets * PKT_BITS / (elapsed / 1000.0) / 1000.0 if elapsed > 0 else 0
    res = dict(protocol=a.protocol.upper(), transmitted=sim.stats["tx"],
               retransmissions=sim.stats["rtx"], delivered=len(rcv.delivered),
               correct=ok, time_ms=round(elapsed, 1),
               throughput_kbps=round(thr, 2), timeouts=sim.stats["timeouts"],
               **{k: v for k, v in sim.stats.items()
                  if k in ("acks", "lost_data", "lost_ack", "corrupt_data",
                           "corrupt_ack", "delayed")})
    return res

def parse(argv=None):
    p = argparse.ArgumentParser(description="GBN / SR over an unreliable channel")
    p.add_argument("--protocol", choices=["gbn", "sr"], default="gbn")
    p.add_argument("--packets", type=int, default=200)
    p.add_argument("--window", type=int, default=4, help="window size N")
    p.add_argument("--bits", type=int, default=3, help="sequence-number bits k")
    p.add_argument("--loss", type=float, default=0.0)
    p.add_argument("--corrupt", type=float, default=0.0)
    p.add_argument("--delay", type=float, default=0.0, help="delay probability")
    p.add_argument("--max_extra_delay", type=float, default=150.0, help="ms")
    p.add_argument("--timeout", type=float, default=700.0, help="ms")
    p.add_argument("--seed", type=int, default=918)
    p.add_argument("--drop", default="", help="comma list of data packet numbers whose "
                   "FIRST transmission is forcibly lost (for the Task 2 trace)")
    p.add_argument("--quiet", action="store_true", help="no per-event log")
    return p.parse_args(argv)

def main():
    a = parse()
    res = run(a)
    print("\n========== SUMMARY ==========")
    print(f"protocol={res['protocol']}  packets={a.packets}  N={a.window}  "
          f"k={a.bits}  seed={a.seed}")
    print(f"loss={a.loss} corrupt={a.corrupt} delay={a.delay} timeout={a.timeout} ms")
    print(f"data packets transmitted : {res['transmitted']}")
    print(f"retransmissions          : {res['retransmissions']}")
    print(f"timeouts                 : {res['timeouts']}")
    print(f"delivered to application : {res['delivered']}  (in order & correct: {res['correct']})")
    print(f"channel: lost data={res['lost_data']} lost ack={res['lost_ack']} "
          f"corrupt data={res['corrupt_data']} corrupt ack={res['corrupt_ack']} "
          f"delayed={res['delayed']}")
    print(f"completion time          : {res['time_ms']} ms")
    print(f"throughput               : {res['throughput_kbps']} kbps")


if __name__ == "__main__":
    main()
