"""Simulated e-commerce world (ALL DATA IS SIMULATED).

The world is a stateless, seeded generator: ``World(state, customers).export(until)`` regenerates every
record visible at ``until``. Hidden causal *factors* (e.g. a bad delivery partner) shape outcomes; the
investigating agents never import this module - they only see the exported rows after ingestion.
When time advances, factors change (interventions, injected evidence) or new feeds are connected, the
changed rows re-enter the platform as new revisions of existing records.
"""
from __future__ import annotations

import zlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.sim import text_bank as tb

CITIES = {"Mumbai": ("West", 0.22), "Delhi": ("North", 0.20), "Bengaluru": ("South", 0.19),
          "Chennai": ("South", 0.14), "Pune": ("West", 0.13), "Jaipur": ("North", 0.12)}
TIER2 = {"Pune", "Jaipur"}
BASE_PARTNER = {"Mumbai": "QuickParcel", "Delhi": "RapidRoute", "Bengaluru": "QuickParcel",
                "Chennai": "EkartX", "Pune": "EkartX", "Jaipur": "RapidRoute"}
PROMISE_HOURS = {"Mumbai": 48, "Delhi": 60, "Bengaluru": 48, "Chennai": 60, "Pune": 60, "Jaipur": 72}
TRAFFIC_BASE = {"Mumbai": 52, "Delhi": 50, "Bengaluru": 55, "Chennai": 44, "Pune": 40, "Jaipur": 35}
PAY_METHODS = ["UPI", "Card", "COD", "Wallet", "NetBanking"]
PAY_W = [0.45, 0.30, 0.12, 0.08, 0.05]
GATEWAY = {"UPI": "UPI-Rail", "Card": "PayFast", "NetBanking": "BankConnect", "Wallet": "WalletPay", "COD": ""}
ANDROID_OS = ["Android 12", "Android 13", "Android 14"]
SEGMENTS = [
    ("NEW_JOINERS", "New Joiners", "Customers with under 90 days of tenure", "tenure_days < 90"),
    ("PREMIUM_METRO", "Premium Metro Loyalists", "Premium plan customers in metro cities", "plan = premium"),
    ("TIER2_HOUSEHOLDS", "Tier-2 Households", "Customers in tier-2 cities", "city in (Pune, Jaipur)"),
    ("URBAN_REGULARS", "Urban Regulars", "Plus plan customers in metro cities", "plan = plus"),
    ("VALUE_SEEKERS", "Value Seekers", "Free plan, discount-driven shoppers", "plan = free"),
]

_CATALOG = [
    ("Electronics", ["Wireless Earbuds", "Bluetooth Speaker", "Smartwatch", "Power Bank 20000mAh", "USB-C Fast Charger",
                     "Webcam HD", "Gaming Mouse", "Noise Cancelling Headphones"], ["SoundWave Ltd", "VoltEdge"], 2500),
    ("Small Appliances", [("Mixer Grinder 500W", "Apex Home Appliances"), ("Electric Kettle 1.8L", "Apex Home Appliances"),
                          ("Induction Cooktop", "Apex Home Appliances"), ("Air Fryer 4L", "Brightline Electricals"),
                          ("Hand Blender", "Kitchenkraft"), ("Sandwich Maker", "Kitchenkraft")], [], 2800),
    ("Fashion", ["Cotton T-Shirt", "Slim Fit Jeans", "Running Shoes", "Formal Shirt", "Hoodie", "Handbag", "Wrist Watch",
                 "Sunglasses"], ["UrbanThread", "StyleHub"], 1600),
    ("Home & Kitchen", ["Non-stick Cookware Set", "Bedsheet Set", "LED Desk Lamp", "Storage Containers", "Wall Clock",
                        "Cushion Covers"], ["HomeNest", "Kitchenkraft"], 1400),
    ("Beauty", ["Face Serum", "Hair Dryer", "Beard Trimmer", "Perfume 100ml"], ["GlowLab", "PureLeaf"], 1200),
    ("Grocery", ["Organic Tea 500g", "Almonds 1kg", "Olive Oil 1L", "Protein Bar Pack"], ["FreshFarm"], 700),
]


def build_skus() -> list[dict]:
    rng = np.random.default_rng(11)
    out, n = [], 100
    for cat, items, suppliers, price in _CATALOG:
        for it in items:
            n += 1
            name, sup = it if isinstance(it, tuple) else (it, suppliers[n % len(suppliers)])
            out.append({"sku": f"{cat[:2].upper()}-{n}", "name": name, "category": cat, "supplier": sup,
                        "price": round(float(price * rng.uniform(0.5, 1.5)), 0), "batch": "B-2105"})
    return out


SKUS = build_skus()
APEX_SKUS = [s["sku"] for s in SKUS if s["supplier"] == "Apex Home Appliances"]


def _h(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def _seed(*parts) -> np.random.Generator:
    return np.random.default_rng(_h(*parts))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def make_customers(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    names, w = list(CITIES), np.array([c[1] for c in CITIES.values()])
    city = rng.choice(names, n, p=w / w.sum())
    plan = rng.choice(["free", "plus", "premium"], n, p=[0.5, 0.35, 0.15])
    tenure = np.clip(rng.gamma(2.2, 260, n), 5, 2400).astype(int)
    mult = np.select([plan == "premium", plan == "plus"], [2.4, 1.4], 0.8)
    ltv = np.round(rng.lognormal(8.3, 0.6, n) * mult * np.clip(tenure / 400, 0.3, 3), 0)
    platform = rng.choice(["Android", "iOS", "Web"], n, p=[0.55, 0.33, 0.12])
    os_v = np.where(platform == "Android", rng.choice(ANDROID_OS, n, p=[0.3, 0.35, 0.35]),
                    np.where(platform == "iOS", rng.choice(["iOS 17", "iOS 18"], n, p=[0.4, 0.6]), ""))
    seg = []
    for t, p, c in zip(tenure, plan, city):
        seg.append("NEW_JOINERS" if t < 90 else "PREMIUM_METRO" if p == "premium" else "TIER2_HOUSEHOLDS" if c in TIER2
                   else "URBAN_REGULARS" if p == "plus" else "VALUE_SEEKERS")
    df = pd.DataFrame({
        "customer_id": [f"CUST-{i + 1:05d}" for i in range(n)], "city": city, "region": [CITIES[c][0] for c in city],
        "plan": plan, "tenure_days": tenure, "lifetime_value": ltv, "platform": platform, "os_version": os_v,
        "segment_code": seg,
    })
    df["orders_90d"] = rng.poisson(np.select([plan == "premium", plan == "plus"], [9, 5], 2.5))
    df["complaints_90d"] = 0
    return df


def default_state(anchor: datetime, seed: int = 7) -> dict:
    """Initial hidden world. ``anchor`` = simulated 'now' (midnight); history covers the 30 days before it."""
    start = anchor - timedelta(days=30)
    day = lambda d, h=0: iso(start + timedelta(days=d, hours=h))  # noqa: E731
    return {
        "seed": seed, "start": iso(start), "days_history": 30,
        "factors": [
            {"id": "F-PARTNER-SWIFTSHIP", "issue": "delivery", "cause_type": "logistics_partner_change", "truth": True,
             "label": "New last-mile partner SwiftShip performs poorly in Mumbai", "target": "late_prob", "add": 0.42,
             "scope": {"delivery_partner": ["SwiftShip"]}, "start": day(16, 9), "ramp_days": 2,
             "voice": {"aspect": "delivery", "theme": "partner", "p": 0.35}},
            {"id": "F-TRAFFIC-MUMBAI", "issue": "delivery", "cause_type": "traffic_congestion", "truth": False,
             "label": "Eastern Freeway repair congestion in Mumbai (minor contributor)", "target": "late_prob", "add": 0.05,
             "scope": {"city": ["Mumbai"]}, "start": day(16), "ramp_days": 1,
             "metrics": [{"metric": "traffic_congestion_index", "add": 11, "entity": ["Mumbai"]}],
             "voice": {"aspect": "delivery", "theme": "traffic", "p": 0.3}},
            {"id": "F-GATEWAY-PAYFAST", "issue": "payment", "cause_type": "gateway_degradation", "truth": True,
             "label": "PayFast card gateway 3DS timeouts", "target": "payment_fail_prob", "add": 0.20,
             "scope": {"payment_method": ["Card"]}, "start": day(23, 6), "ramp_days": 0.5, "failure_code": "GATEWAY_TIMEOUT",
             "metrics": [{"metric": "gateway_availability", "add": -3.2, "entity": ["PayFast"]}],
             "voice": {"aspect": "payment", "theme": "gateway", "p": 0.5}},
            {"id": "F-RELEASE-APP780", "issue": "app", "cause_type": "release_regression", "truth": True,
             "label": "Mobile app 7.8.0 crashes on Android 14", "target": "crash_rate_add", "add": 0.055,
             "scope": {"app_version": ["7.8.0"], "os_version": ["Android 14"]}, "start": day(21, 8), "ramp_days": 0,
             "voice": {"aspect": "app", "theme": "release", "p": 0.6}},
            {"id": "F-SUPPLIER-APEX", "issue": "product_quality", "cause_type": "supplier_quality", "truth": True,
             "label": "Apex Home Appliances batch B-2207 heating element defect", "target": "defect_prob", "add": 0.30,
             "scope": {"supplier": ["Apex Home Appliances"], "batch": ["B-2207"]}, "start": day(12), "ramp_days": 0,
             "voice": {"aspect": "product_quality", "theme": "supplier", "p": 0.5}},
            {"id": "F-REFUND-MIGRATION", "issue": "refund", "cause_type": "refund_pipeline_backlog", "truth": True,
             "label": "Refund service v2 ledger migration stalls card refunds", "target": "refund_delay_hours", "add": 110,
             "scope": {"refund_type": ["original"]}, "start": day(17), "ramp_days": 1,
             "metrics": [{"metric": "refund_queue_depth", "add": 260, "entity": ["refund-service"]}],
             "voice": {"aspect": "refund", "theme": "backlog", "p": 0.6}},
            {"id": "F-STAFFING-DECOY", "issue": None, "cause_type": "support_capacity", "truth": False,
             "label": "Holiday roster reduces support agents (no KPI effect)", "target": None, "start": day(20), "end": day(24),
             "metrics": [{"metric": "support_backlog", "add": 35, "entity": ["support"]}]},
        ],
        "partner_rollouts": [{"partner": "SwiftShip", "city": "Mumbai", "start": day(16, 9), "share": 0.55, "ramp_days": 2}],
        "app_rollouts": [{"version": "7.8.0", "platform": "Android", "start": day(21, 8), "max_share": 0.75, "ramp_days": 4,
                          "replaces": "7.7.4"}],
        "supplier_batches": [{"supplier": "Apex Home Appliances", "from": day(12), "batch": "B-2207"}],
        "promo_days": [4, 11, 18, 25],
        "feeds": ["traffic_congestion_index", "gateway_availability", "refund_queue_depth", "support_backlog", "api_p95_latency_ms"],
        "voice_mults": [], "extra_events": [],
    }


class World:
    def __init__(self, state: dict, customers: pd.DataFrame):
        self.s = state
        self.seed = state["seed"]
        self.start = parse(state["start"])
        self.cust = customers.sort_values("customer_id").reset_index(drop=True)
        plan_w = self.cust["plan"].map({"premium": 2.0, "plus": 1.2, "free": 0.8}).to_numpy(float)
        ltv = self.cust["lifetime_value"].to_numpy(float)
        w = plan_w * (0.5 + ltv / max(ltv.mean(), 1.0))
        self.prop = w / w.sum()
        self.factors = [dict(f) for f in state["factors"]]  # private copies: parsed helpers must not leak into persisted state
        for f in self.factors:
            f["_st"] = parse(f["start"])
            f["_end"] = parse(f["end"]) if f.get("end") else None
            f["_mit"] = [(parse(m["from"]), m["eff"], parse(m["until"]) if m.get("until") else None) for m in f.get("mitigations", [])]
        self.sku_w = np.array([2.0 if s["sku"] in APEX_SKUS else 1.0 for s in SKUS])
        self.sku_w = self.sku_w / self.sku_w.sum()

    # ---- hidden-factor mechanics -------------------------------------------------------------------------
    def strength(self, f: dict, t: datetime) -> float:
        if t < f["_st"] or (f["_end"] and t >= f["_end"]):
            return 0.0
        ramp = f.get("ramp_days") or 0
        s = 1.0 if not ramp else min(1.0, (t - f["_st"]).total_seconds() / 86400 / ramp)
        for frm, eff, until in f["_mit"]:
            if t >= frm and (until is None or t < until):
                s *= 1 - eff
        return s

    @staticmethod
    def _match(scope: dict | None, attrs: dict) -> bool:
        return all(attrs.get(k) in (v if isinstance(v, list) else [v]) for k, v in (scope or {}).items())

    def _components(self, target: str, base: float, t: datetime, attrs: dict):
        comps = [(None, base)]
        for f in self.factors:
            if f.get("target") == target and self._match(f.get("scope"), attrs):
                s = self.strength(f, t)
                if s > 0:
                    comps.append((f, f["add"] * s))
        return comps

    @staticmethod
    def _draw(rng, comps, cap=0.95):
        p = min(cap, sum(c for _, c in comps))
        if rng.random() >= p:
            return False, None
        r, acc = rng.random() * sum(c for _, c in comps), 0.0
        for f, c in comps:
            acc += c
            if r <= acc:
                return True, f
        return True, comps[-1][0]

    def metric_adds(self, metric: str, entity: str, t: datetime) -> float:
        total = 0.0
        for f in self.factors:
            for m in f.get("metrics", []):
                if m["metric"] == metric and entity in m["entity"]:
                    total += m["add"] * self.strength(f, t)
        return total

    # ---- helpers -----------------------------------------------------------------------------------------
    def _partner(self, city: str, t: datetime, rng) -> str:
        partner = BASE_PARTNER[city]
        for ro in self.s["partner_rollouts"]:
            st = parse(ro["start"])
            if ro["city"] == city and t >= st:
                share = ro["share"] * min(1.0, (t - st).total_seconds() / 86400 / max(ro["ramp_days"], 0.01))
                if rng.random() < share:
                    partner = ro["partner"]
        return partner

    def _app_version(self, platform: str, t: datetime, rng) -> str:
        if platform == "iOS":
            return "7.7.5"
        if platform == "Web":
            return "web-14.2"
        v = "7.7.4"
        for ro in self.s["app_rollouts"]:
            st = parse(ro["start"])
            if ro["platform"] == platform and t >= st:
                if rng.random() < ro["max_share"] * min(1.0, (t - st).total_seconds() / 86400 / max(ro["ramp_days"], 0.01)):
                    v = ro["version"]
        return v

    def _batch(self, sku: dict, t: datetime) -> str:
        b = sku["batch"]
        for sb in self.s["supplier_batches"]:
            if sb["supplier"] == sku["supplier"] and t >= parse(sb["from"]):
                b = sb["batch"]
        return b

    def _voice_mult(self, aspect: str, t: datetime) -> float:
        m = 1.0
        for vm in self.s.get("voice_mults", []):
            if vm["aspect"] in (aspect, "*") and t >= parse(vm["from"]) and (not vm.get("until") or t < parse(vm["until"])):
                m *= vm["mult"]
        return m

    def _theme(self, rng, aspect: str, cause) -> str:
        v = (cause or {}).get("voice")
        if v and v["aspect"] == aspect and rng.random() < v["p"]:
            return v["theme"]
        return "generic"

    # ---- record builders ---------------------------------------------------------------------------------
    def _order(self, d: int, i: int, cidx: int, until: datetime):
        rng = _seed(self.seed, "ord", d, i)
        c = self.cust.iloc[cidx]
        day0 = self.start + timedelta(days=d)
        t0 = day0 + timedelta(hours=float(rng.uniform(7, 23)))
        sku = SKUS[int(rng.choice(len(SKUS), p=self.sku_w))]
        city = c["city"]
        method = str(rng.choice(PAY_METHODS, p=PAY_W))
        platform = c["platform"]
        attrs = {"city": city, "delivery_partner": self._partner(city, t0, rng), "payment_method": method,
                 "gateway": GATEWAY[method], "app_version": self._app_version(platform, t0, rng), "platform": platform,
                 "os_version": c["os_version"], "sku": sku["sku"], "supplier": sku["supplier"], "batch": self._batch(sku, t0),
                 "category": sku["category"], "plan": c["plan"]}
        qty = int(rng.choice([1, 1, 1, 2, 3]))
        amount = float(round(sku["price"] * qty * rng.uniform(0.92, 1.05), 0))
        row = {"order_id": f"ORD-{d:03d}-{i:04d}", "customer_id": c["customer_id"], "order_at": iso(t0), "sku": sku["sku"],
               "product_name": sku["name"], "category": sku["category"], "supplier": sku["supplier"], "batch": attrs["batch"],
               "amount": amount, "payment_method": method, "gateway": attrs["gateway"], "payment_status": "success",
               "failure_code": "", "recovered_by_retry": "", "app_version": attrs["app_version"], "platform": platform,
               "os_version": c["os_version"], "city": city, "warehouse": f"{city}-FC", "delivery_partner": attrs["delivery_partner"],
               "promised_at": "", "delivered_at": "", "delivery_status": "not_shipped", "return_status": "none",
               "return_reason": "", "refund_requested_at": "", "refund_completed_at": "", "refund_type": "", "refund_amount": ""}
        voices, survey = [], None
        ctx = {"product": sku["name"], "city": city, "partner": attrs["delivery_partner"], "customer_id": c["customer_id"],
               "platform": platform}

        failed, cause = False, None
        if method != "COD":
            failed, cause = self._draw(rng, self._components("payment_fail_prob", 0.025, t0, attrs))
        if failed:
            row["payment_status"] = "failed"
            row["failure_code"] = (cause or {}).get("failure_code") or str(rng.choice(
                ["BANK_DECLINED", "INSUFFICIENT_FUNDS", "USER_ABORT", "OTP_MISMATCH"]))
            row["recovered_by_retry"] = int(rng.random() < (0.25 if cause else 0.45))
            if rng.random() < 0.35:
                voices.append(dict(aspect="payment", theme=self._theme(rng, "payment", cause), t=t0 + timedelta(hours=float(rng.uniform(0.1, 3))), **ctx))
            return row, voices, None

        if rng.random() < 0.015:
            row["delivery_status"] = "cancelled"
            return row, voices, None

        ph = PROMISE_HOURS[city]
        promised = t0 + timedelta(hours=ph)
        late, lcause = self._draw(rng, self._components("late_prob", 0.06, t0, attrs))
        delivered = promised + timedelta(hours=float(rng.uniform(6, 60))) if late else t0 + timedelta(hours=float(ph * rng.uniform(0.55, 0.93)))
        row["promised_at"] = iso(promised)
        known_delivery = delivered <= until
        row["delivered_at"] = iso(delivered) if known_delivery else ""
        row["delivery_status"] = "delivered" if known_delivery else "in_transit"
        if late and rng.random() < 0.55:
            days = max(1, int(((delivered if known_delivery else until) - promised).total_seconds() // 86400) + 1)
            voices.append(dict(aspect="delivery", theme=self._theme(rng, "delivery", lcause), days=days,
                               t=promised + timedelta(hours=float(rng.uniform(1, 30))), **ctx))
        defective_return = other_return = False
        dcause = None
        if known_delivery:
            defective_return, dcause = self._draw(rng, self._components("defect_prob", 0.015, t0, attrs))
            other_return = (not defective_return) and rng.random() < 0.04
        if defective_return or other_return:
            ret_at = delivered + timedelta(days=float(rng.uniform(1, 5) if defective_return else rng.uniform(2, 9)))
            if ret_at <= until:
                row["return_status"] = "returned"
                row["return_reason"] = "defective" if defective_return else str(rng.choice(["size_issue", "changed_mind", "wrong_item"]))
                if defective_return and rng.random() < 0.6:
                    voices.append(dict(aspect="product_quality", theme=self._theme(rng, "product_quality", dcause),
                                       t=ret_at + timedelta(hours=float(rng.uniform(0, 20))), **ctx))
                req = ret_at + timedelta(hours=float(rng.uniform(1, 6)))
                rtype = "wallet" if rng.random() < 0.35 else "original"
                rattrs = {**attrs, "refund_type": rtype}
                if rtype == "wallet":
                    dur = float(rng.uniform(0.5, 3))
                    rcause = None
                else:
                    dur = max(12.0, float(np.exp(rng.normal(np.log(48), 0.4))))
                    comps = [(f, f["add"] * self.strength(f, req)) for f in self.factors
                             if f.get("target") == "refund_delay_hours" and self._match(f.get("scope"), rattrs)
                             and self.strength(f, req) > 0]
                    rcause = comps[0][0] if comps else None
                    dur += sum(c for _, c in comps) * float(rng.uniform(0.8, 1.2))
                row["refund_requested_at"] = iso(req)
                row["refund_type"] = rtype
                row["refund_amount"] = amount
                done = req + timedelta(hours=dur)
                row["refund_completed_at"] = iso(done) if done <= until else ""
                sla = timedelta(hours=120)
                if (done - req) > sla and req + sla <= until and rng.random() < 0.55:
                    voices.append(dict(aspect="refund", theme=self._theme(rng, "refund", rcause),
                                       days=max(5, int((until - req).total_seconds() // 86400) if done > until else int(dur // 24)),
                                       t=req + sla + timedelta(hours=float(rng.uniform(2, 48))), **ctx))
        if known_delivery and rng.random() < 0.045:
            st = delivered + timedelta(hours=float(rng.uniform(2, 48)))
            csat = float(np.clip(rng.normal(4.3, 0.6) - (1.8 if late else 0) - (2.0 if defective_return else 0), 1, 5))
            survey = {"customer_id": c["customer_id"], "t": st, "csat": round(csat), "city": city, "late": late}
        return row, voices, survey

    def _render(self, v: dict, rng) -> str:
        bank = tb.NEG.get((v["aspect"], v["theme"])) or tb.NEG[(v["aspect"], "generic")]
        text = bank[int(rng.integers(len(bank)))].format(
            product=v.get("product", "order"), days=v.get("days", int(rng.integers(2, 6))),
            partner=v.get("partner", "the courier"), city=v.get("city", ""))
        return text + tb.SUFFIX[int(rng.integers(len(tb.SUFFIX)))]

    def _voice_rows(self, voices: list[dict], until: datetime, out: dict, key: str):
        """Turn voice events into review / ticket / social rows (deterministic by key)."""
        for k, v in enumerate(voices):
            if v["t"] > until or v["t"] < self.start:
                continue
            rng = _seed(self.seed, "voice", key, k)
            if rng.random() > self._voice_mult(v["aspect"], v["t"]):
                continue
            text = self._render(v, rng)
            ch = rng.random()
            cust = v["customer_id"]
            rows = [("review" if ch < 0.4 else "ticket" if ch < 0.82 else "social", v["t"], text)]
            if rng.random() < 0.06:  # same customer re-posts on another channel -> duplicate report
                rows.append(("social" if rows[0][0] != "social" else "review", v["t"] + timedelta(hours=float(rng.uniform(1, 20))),
                             "Again: " + text if rng.random() < 0.5 else text))
            for j, (kind, t, tx) in enumerate(rows):
                if t > until:
                    continue
                self._append_voice(out, kind, f"{key}-{k}-{j}", cust, t, tx, v, rng)

    def _append_voice(self, out, kind, key, cust, t, text, v, rng):
        city = v.get("city", "")
        if kind == "review":
            out["reviews"].append({"review_id": f"REV-{key}", "customer_id": cust, "timestamp": iso(t), "product": v.get("product", ""),
                                   "rating": int(rng.choice([1, 1, 2, 2, 3], p=[0.35, 0.3, 0.2, 0.1, 0.05])), "review_text": text,
                                   "city": city, "platform": v.get("platform", "")})
        elif kind == "ticket":
            med = 20 * (2.2 if v["aspect"] == "refund" and v["theme"] == "backlog" else 1.0)
            res = t + timedelta(hours=float(np.exp(rng.normal(np.log(med), 0.6))))
            cat = {"delivery": "delivery", "payment": "payment", "app": "app", "product_quality": "product", "refund": "refund",
                   "support": "support", "pricing": "billing", "packaging": "delivery"}[v["aspect"]]
            out["tickets"].append({"ticket_id": f"TKT-{key}", "customer_id": cust, "created_at": iso(t),
                                   "channel": str(rng.choice(["app", "email", "phone", "chat"])), "category": cat,
                                   "subject": text[:60], "description": text,
                                   "priority": str(rng.choice(["low", "medium", "high"], p=[0.3, 0.5, 0.2])),
                                   "status": "resolved" if res <= self._until else "open",
                                   "resolved_at": iso(res) if res <= self._until else "", "product": v.get("product", "")})
        else:
            anon = rng.random() < 0.7
            out["social"].append({"post_id": f"SOC-{key}", "handle_hash": f"h{_h(cust, key) % 10**8:08d}",
                                  "customer_id": "" if anon else cust, "timestamp": iso(t),
                                  "platform": str(rng.choice(["x", "facebook", "instagram"])), "text": text,
                                  "likes": int(rng.poisson(3)), "city": city})

    # ---- export ------------------------------------------------------------------------------------------
    def export(self, until: datetime) -> dict[str, pd.DataFrame]:
        self._until = until
        out = {k: [] for k in ["reviews", "tickets", "social", "surveys", "transactions", "telemetry", "metrics"]}
        n_days = int(np.ceil((until - self.start).total_seconds() / 86400))
        cities = self.cust["city"].to_numpy()
        for d in range(n_days):
            day0 = self.start + timedelta(days=d)
            drng = _seed(self.seed, "day", d)
            lam = 100 * (1.15 if day0.weekday() >= 5 else 1.0) * (1.3 if d in self.s["promo_days"] else 1.0)
            n = int(drng.poisson(lam))
            cidx = drng.choice(len(self.cust), n, p=self.prop)
            for i in range(n):
                row, voices, survey = self._order(d, i, int(cidx[i]), until)
                if row["order_at"] >= iso(until):
                    continue
                out["transactions"].append(row)
                for v in voices:
                    v["day"] = d
                self._voice_rows(voices, until, out, f"{row['order_id']}")
                if survey and survey["t"] <= until:
                    r = _seed(self.seed, "survey", row["order_id"])
                    csat = survey["csat"]
                    out["surveys"].append({"response_id": f"SRV-{row['order_id']}", "customer_id": survey["customer_id"],
                                           "timestamp": iso(survey["t"]), "nps": int(np.clip(round((csat - 1) * 2.5), 0, 10)),
                                           "csat": csat, "comment": str(r.choice(tb.SURVEY_COMMENTS_NEG if csat <= 3 else tb.SURVEY_COMMENTS_POS)),
                                           "city": survey["city"]})
            self._background_day(d, day0, until, out, cities)
            self._telemetry_day(d, day0, until, out)
            self._metrics_day(d, day0, until, out)
        self._injection_samples(until, out)
        frames = {k: pd.DataFrame(v) for k, v in out.items()}
        frames["events"] = pd.DataFrame(self.events(until))
        frames["releases"] = pd.DataFrame(self.releases(until))
        return frames

    def _pick_customers(self, rng, k, mask=None):
        p = self.prop if mask is None else self.prop * mask
        return rng.choice(len(self.cust), k, p=p / p.sum())

    def _background_day(self, d, day0, until, out, cities):
        bg = {"delivery": 0.6, "payment": 0.5, "app": 0.9, "product_quality": 2.0, "refund": 1.2, "support": 3.0, "pricing": 1.5,
              "packaging": 0.7}
        if d in (15, 16):
            bg["pricing"] += 2.0  # decoy: short-lived price-complaint blip
        voices = []
        for a, (aspect, lam) in enumerate(bg.items()):
            rng = _seed(self.seed, "bg", d, a)
            for c in self._pick_customers(rng, int(rng.poisson(lam))):
                cr = self.cust.iloc[int(c)]
                voices.append(dict(aspect=aspect, theme="generic", t=day0 + timedelta(hours=float(rng.uniform(6, 24))), days=int(rng.integers(2, 5)),
                                   customer_id=cr["customer_id"], city=cr["city"], platform=cr["platform"],
                                   product=SKUS[int(rng.integers(len(SKUS)))]["name"], partner=BASE_PARTNER[cr["city"]]))
        if d == 27:  # decoy: one-day social burst about packaging (viral post, not sustained)
            rng = _seed(self.seed, "burst", d)
            for c in self._pick_customers(rng, 9):
                cr = self.cust.iloc[int(c)]
                voices.append(dict(aspect="packaging", theme="generic", t=day0 + timedelta(hours=float(rng.uniform(9, 16))), customer_id=cr["customer_id"],
                                   city=cr["city"], platform=cr["platform"], product="order", partner="", force="social"))
        # positives / neutrals (not complaints)
        rng = _seed(self.seed, "pos", d)
        for kind, lam, bank in (("pos", 11, tb.POSITIVE), ("neu", 2, tb.NEUTRAL)):
            for k, c in enumerate(self._pick_customers(rng, int(rng.poisson(lam)))):
                cr = self.cust.iloc[int(c)]
                t = day0 + timedelta(hours=float(rng.uniform(6, 24)))
                if t > until:
                    continue
                text = bank[int(rng.integers(len(bank)))].format(product=SKUS[int(rng.integers(len(SKUS)))]["name"])
                if rng.random() < 0.75:
                    out["reviews"].append({"review_id": f"REV-{kind}-{d}-{k}", "customer_id": cr["customer_id"], "timestamp": iso(t), "product": "",
                                           "rating": int(rng.choice([4, 5] if kind == "pos" else [3, 4])), "review_text": text,
                                           "city": cr["city"], "platform": cr["platform"]})
                else:
                    out["social"].append({"post_id": f"SOC-{kind}-{d}-{k}", "handle_hash": f"h{_h(cr['customer_id'], d, k) % 10**8:08d}",
                                          "customer_id": "", "timestamp": iso(t), "platform": "x", "text": text, "likes": int(rng.poisson(2)),
                                          "city": cr["city"]})
        rng = _seed(self.seed, "inq", d)
        for k in range(int(rng.poisson(2))):
            cr = self.cust.iloc[int(self._pick_customers(rng, 1)[0])]
            t = day0 + timedelta(hours=float(rng.uniform(7, 22)))
            if t <= until:
                out["tickets"].append({"ticket_id": f"TKT-INQ-{d}-{k}", "customer_id": cr["customer_id"], "created_at": iso(t), "channel": "chat",
                                       "category": "inquiry", "subject": "Question about my account", "description":
                                       str(rng.choice(["How do I change my delivery address?", "Can I update my phone number on the account?",
                                                       "Where can I download my invoice?"])),
                                       "priority": "low", "status": "resolved", "resolved_at": iso(t + timedelta(hours=4)), "product": ""})
        self._voice_rows([v for v in voices if not v.get("force")], until, out, f"bg{d}")
        for k, v in enumerate([v for v in voices if v.get("force")]):
            rng = _seed(self.seed, "burst-voice", d, k)
            if v["t"] <= until:
                self._append_voice(out, "social", f"burst{d}-{k}", v["customer_id"], v["t"], self._render(v, rng), v, rng)

    def _telemetry_day(self, d, day0, until, out):
        t_mid = day0 + timedelta(hours=12)
        if t_mid > until:
            return
        rng = _seed(self.seed, "tel", d)
        shares = {"Android": 0.55, "iOS": 0.33, "Web": 0.12}
        combos = []
        for plat, sh in shares.items():
            oses = {"Android": ANDROID_OS, "iOS": ["iOS 17", "iOS 18"], "Web": [""]}[plat]
            w = {"Android": [0.3, 0.35, 0.35], "iOS": [0.4, 0.6], "Web": [1.0]}[plat]
            for o, ow in zip(oses, w):
                if plat == "Android":
                    s780 = 0.0
                    for ro in self.s["app_rollouts"]:
                        st = parse(ro["start"])
                        if t_mid >= st:
                            s780 = ro["max_share"] * min(1.0, (t_mid - st).total_seconds() / 86400 / max(ro["ramp_days"], 0.01))
                    combos += [(plat, o, "7.7.4", sh * ow * (1 - s780)), (plat, o, "7.8.0", sh * ow * s780)]
                else:
                    combos.append((plat, o, "7.7.5" if plat == "iOS" else "web-14.2", sh * ow))
        for plat, osv, ver, share in combos:
            sessions = int(rng.poisson(3500 * share))
            if sessions == 0:
                continue
            attrs = {"platform": plat, "os_version": osv, "app_version": ver}
            base = {"Android": 0.004, "iOS": 0.0025, "Web": 0.0015}[plat]
            p = min(0.5, sum(c for _, c in self._components("crash_rate_add", base, t_mid, attrs)))
            crashes = int(rng.binomial(sessions, p))
            out["telemetry"].append({"date": day0.strftime("%Y-%m-%d"), "app_version": ver, "platform": plat, "os_version": osv,
                                     "sessions": sessions, "crashes": crashes, "p95_latency_ms": int(rng.normal(820, 60))})
            # crash-driven complaints
            cv = []
            idx = self.cust.index[(self.cust["platform"] == plat) & (self.cust["os_version"] == osv)]
            if len(idx):
                for k in range(int(rng.binomial(crashes, 0.07))):
                    cr = self.cust.iloc[int(rng.choice(idx))]
                    cause = next((f for f in self.factors if f.get("target") == "crash_rate_add" and self._match(f.get("scope"), attrs)
                                  and self.strength(f, t_mid) > 0), None)
                    cv.append(dict(aspect="app", theme=self._theme(rng, "app", cause), t=day0 + timedelta(hours=float(rng.uniform(6, 24))),
                                   customer_id=cr["customer_id"], city=cr["city"], platform=plat, product="", partner=""))
            self._voice_rows(cv, until, out, f"crash{d}-{ver}-{osv.replace(' ', '')}-{plat}")

    def _metrics_day(self, d, day0, until, out):
        t = day0 + timedelta(hours=12)
        if t > until:
            return
        rng = _seed(self.seed, "met", d)
        date = day0.strftime("%Y-%m-%d")
        feeds = self.s["feeds"]

        def add(metric, entity_type, entity, value, unit):
            if metric in feeds:
                out["metrics"].append({"date": date, "metric_name": metric, "entity_type": entity_type, "entity": entity,
                                       "value": round(float(value), 2), "unit": unit})

        for city, base in TRAFFIC_BASE.items():
            add("traffic_congestion_index", "city", city, base + rng.normal(0, 3.5) + (4 if day0.weekday() < 5 else -3) + self.metric_adds("traffic_congestion_index", city, t), "index")
        for gw in ["UPI-Rail", "PayFast", "BankConnect", "WalletPay"]:
            add("gateway_availability", "gateway", gw, min(100.0, 99.8 + rng.normal(0, 0.08) + self.metric_adds("gateway_availability", gw, t)), "%")
        add("refund_queue_depth", "service", "refund-service", max(0.0, 40 + rng.normal(0, 8) + self.metric_adds("refund_queue_depth", "refund-service", t)), "items")
        add("support_backlog", "team", "support", max(0.0, 120 + rng.normal(0, 14) + self.metric_adds("support_backlog", "support", t)), "tickets")
        add("api_p95_latency_ms", "service", "api", 320 + rng.normal(0, 25), "ms")
        for city in CITIES:
            add("warehouse_dispatch_hours", "warehouse", f"{city}-FC", max(0.5, 3.1 + rng.normal(0, 0.3) + self.metric_adds("warehouse_dispatch_hours", f"{city}-FC", t)), "hours")

    def _injection_samples(self, until, out):
        """Adversarial feedback used to demonstrate prompt-injection guardrails (clearly synthetic)."""
        for k, d in enumerate((9, 18, 25)):
            t = self.start + timedelta(days=d, hours=11)
            if t <= until:
                cr = self.cust.iloc[(k * 97) % len(self.cust)]
                out["reviews"].append({"review_id": f"REV-ADV-{k + 1}", "customer_id": cr["customer_id"], "timestamp": iso(t), "product": "",
                                       "rating": 1, "review_text": tb.INJECTION_SAMPLES[k], "city": cr["city"], "platform": cr["platform"]})

    # ---- events & releases ---------------------------------------------------------------------------------
    def events(self, until: datetime) -> list[dict]:
        st = self.start
        e = lambda d, h=0: st + timedelta(days=d, hours=h)  # noqa: E731
        ev = [
            ("EVT-SWIFTSHIP", "partner_change", "SwiftShip onboarded as last-mile partner for Mumbai", "Logistics added SwiftShip for Mumbai West and Central zones; first dispatches began same day.", "SwiftShip", "Mumbai", {"delivery_partner": "SwiftShip", "city": "Mumbai"}, "medium", e(16, 9), None),
            ("EVT-FREEWAY", "traffic_alert", "Eastern Freeway repair lane closures (Mumbai)", "Municipal notice: lane closures on the Eastern Freeway for road repairs.", "Mumbai", "Mumbai", {"city": "Mumbai"}, "medium", e(16), e(29)),
            ("EVT-PAYFAST", "incident", "PayFast card gateway elevated 3DS latency", "Vendor status page: elevated authentication latency and timeouts on card transactions.", "PayFast", "", {"gateway": "PayFast"}, "high", e(23, 6), None),
            ("EVT-CHECKOUT-RETRY", "config_change", "Checkout retry policy updated", "Checkout retry policy changed from 2 to 3 attempts for all payment methods.", "checkout-service", "", {}, "low", e(22, 15), None),
            ("EVT-ANDROID14", "external", "Android 14 security patch rollout", "Staged OS security patch reaching Android 14 devices.", "Android 14", "", {"platform": "Android", "os_version": "Android 14"}, "low", e(20), None),
            ("EVT-APEX-WAIVER", "supplier_change", "Apex Home Appliances switched heating-element vendor", "Supplier changed heating-element vendor under a QC waiver for small appliances.", "Apex Home Appliances", "", {"supplier": "Apex Home Appliances"}, "medium", e(11), None),
            ("EVT-APPLIANCE-SALE", "promotion", "Mega Appliance Sale", "Promotion on small appliances drove higher order volume.", "Small Appliances", "", {"category": "Small Appliances"}, "low", e(12), e(15)),
            ("EVT-REFUND-MIG", "migration", "Refund service v2 ledger migration", "Finance ledger sync moved to refund-service v2; refund batches now run on the new pipeline.", "refund-service", "", {}, "high", e(17), None),
            ("EVT-REFUND-BATCH", "incident", "Refund batch job failures on card rails", "Nightly refund batch intermittently failing for refunds to original payment method.", "refund-service", "", {"refund_type": "original"}, "high", e(18, 2), None),
            ("EVT-STAFFING", "staffing", "Holiday roster: 20% fewer support agents", "Reduced agent availability during regional holidays.", "support", "", {}, "low", e(20), e(24)),
        ]
        cities = list(CITIES)
        rng = np.random.default_rng(self.seed + 5)
        routine = [("maintenance", "Scheduled database maintenance window", "Routine maintenance, no customer impact expected.", "platform-db", ""),
                   ("promotion", "Weekend flash sale campaign", "Marketing campaign with category discounts.", "marketing", ""),
                   ("weather", "Weather advisory: light rain", "Local weather advisory with light rain forecast.", "weather", None),
                   ("warehouse", "Inventory cycle count", "Routine cycle count at the fulfilment centre.", "warehouse", None),
                   ("sla_review", "Partner SLA quarterly review", "Routine SLA review meeting with logistics partners.", "logistics", ""),
                   ("config_change", "Feature flag rollout: wishlist sharing", "Low-risk feature flag change.", "catalog-service", ""),
                   ("traffic_alert", "Routine road work advisory", "Minor road work advisory with no lane closures.", "city-traffic", None),
                   ("deployment", "Minor hotfix deployment", "Non-functional hotfix deployed to the web storefront.", "web-storefront", "")]
        for n in range(96):
            kind, title, desc, entity, city = routine[int(rng.integers(len(routine)))]
            city = str(rng.choice(cities)) if city is None else city
            d = float(rng.uniform(0, 30))
            ev.append((f"EVT-R{n:03d}", kind, f"{title}" + (f" ({city})" if city else ""), desc, entity, city, {"city": city} if city else {},
                       "info", e(0) + timedelta(days=d), None))
        rows = [{"event_id": x[0], "event_type": x[1], "title": x[2], "description": x[3], "entity": x[4], "city": x[5],
                 "scope_json": x[6], "severity": x[7], "start_at": iso(x[8]), "end_at": iso(x[9]) if x[9] else ""} for x in ev]
        rows += self.s.get("extra_events", [])
        return [r for r in rows if parse(r["start_at"]) <= until]

    def releases(self, until: datetime) -> list[dict]:
        st = self.start
        r = [("mobile-app", "7.7.4", 2, "Android maintenance release", "low", {"platform": "Android"}),
             ("refund-service", "1.9.3", 3, "Refund status API fixes", "low", {}),
             ("pricing-engine", "2.2.0", 4, "Coupon stacking rules update", "low", {}),
             ("recommendation", "6.3.0", 5, "Ranking model refresh", "low", {}),
             ("checkout-service", "3.13.2", 6, "Address form validation", "low", {}),
             ("catalog-service", "8.1.0", 8, "Catalog image pipeline", "low", {}),
             ("search", "2.4.0", 9, "Autocomplete improvements", "low", {}),
             ("payments-sdk", "4.2.0", 10, "UPI intent flow cleanup", "medium", {}),
             ("notifications", "1.12.0", 11, "Push notification batching", "low", {}),
             ("ios-app", "7.7.5", 12, "iOS maintenance release", "low", {"platform": "iOS"}),
             ("loyalty", "3.0.0", 13, "Loyalty tiers v3", "medium", {}),
             ("inventory-sync", "1.7.0", 14, "Warehouse stock sync", "low", {}),
             ("support-portal", "4.5.0", 15, "Agent console refresh", "low", {}),
             ("catalog-service", "8.2.0", 16, "Catalog attribute schema", "low", {}),
             ("api-gateway", "12.4.0", 17, "Rate limit tuning", "medium", {}),
             ("refund-service", "2.0.0", 17, "Refund service v2 - new ledger sync and batch processing", "high", {}),
             ("logistics-routing", "5.2.0", 20, "Routing optimiser tweak for last-mile assignment", "medium", {}),
             ("mobile-app", "7.8.0", 21, "Android release: new image gallery library and cart redesign", "high", {"platform": "Android", "app_version": "7.8.0"}),
             ("checkout-service", "3.14.0", 22, "Checkout orchestration refactor", "medium", {}),
             ("auth-service", "5.1.0", 25, "Session token refresh", "low", {}),
             ("web-storefront", "14.2.0", 26, "Storefront performance work", "low", {}),
             ("analytics-pipeline", "9.0.0", 27, "Event pipeline upgrade", "low", {})]
        rows = [{"release_id": f"REL-{i + 1:03d}", "component": c, "version": v, "title": t, "change_summary": t,
                 "deployed_at": iso(st + timedelta(days=d, hours=10)), "scope_json": sc, "rollback_available": True, "risk_level": risk}
                for i, (c, v, d, t, risk, sc) in enumerate(r)]
        return [x for x in rows if parse(x["deployed_at"]) <= until]
