import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from memehunter.analyze import acceleration, evaluate, momentum_score, Tier
from memehunter.config import Thresholds
from memehunter.forensics import rug_scan, grade
from memehunter.hunter import Hunter, State
from memehunter.sources import Pool, GeckoTerminal
from memehunter.storage import archive_cycle
from memehunter.feed import write_feed


def pool(age=30, **kw):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    params = dict(address="0x" + "a"*40, name="CAT / WETH", dex="uniswap-v3-robinhood",
        base_symbol="CAT", base_name="猫", base_address="0x"+"b"*40, quote_symbol="WETH",
        quote_address="0x"+"c"*40, created_at=now-timedelta(minutes=age), observed_at=now,
        liquidity_usd=10000, fdv_usd=20000, market_cap_usd=0, price_usd=1,
        price_change={"h1": 80}, volume={"m5":500, "h1":min(age,60)*100},
        txns={"h1":{"buys":50,"sells":10,"buyers":25,"sellers":8}})
    params.update(kw)
    return Pool(**params)


class RulesTests(unittest.TestCase):
    def test_constant_flow_never_mechanically_accelerates(self):
        for age in [15,30,60,90,1000]:
            self.assertAlmostEqual(acceleration(pool(age)), 1)
            self.assertEqual(momentum_score(pool(age))[1]["acceleration"], 0)

    def test_short_or_missing_history_is_unknown(self):
        for age in [1,5,10,14]: self.assertIsNone(acceleration(pool(age)))
        self.assertIsNone(acceleration(pool(volume={"m5":500})))
        self.assertIsNone(acceleration(pool(volume={"m5":500,"h1":400})))
        self.assertIsNone(acceleration(pool(volume={"m5":500,"h1":500})))

    def test_true_acceleration_uses_disjoint_window(self):
        self.assertAlmostEqual(acceleration(pool(30,volume={"m5":1000,"h1":3500})),2)

    def test_observation_age_is_frozen(self):
        self.assertEqual(pool(30).age_min,30)

    def test_unknown_age_and_missing_data_cap_tier(self):
        for p in [pool(created_at=None),pool(missing_fields=["volume.m5"])]:
            v=evaluate(p,Thresholds())
            self.assertTrue(v.warnings)
            self.assertLessEqual(v.tier,Tier.WATCH)

    def test_capacity_proxy_caps_attention_without_claiming_fill(self):
        v=evaluate(pool(),Thresholds())
        self.assertTrue(any("capacity proxy" in w for w in v.warnings))
        self.assertLessEqual(v.tier,Tier.WATCH)

    def test_v4_never_runs_address_holder_scan(self):
        rpc=Mock()
        g=rug_scan(rpc,"0x"+"b"*40,"0x"+"a"*64,120)
        self.assertFalse(g.scanned)
        self.assertFalse(g.rug_flags)
        rpc.block_number.assert_not_called()
        p=pool(address="0x"+"a"*64,dex="uniswap-v4-robinhood")
        self.assertLessEqual(evaluate(p,Thresholds()).tier,Tier.WATCH)

    def test_small_pool_supply_share_is_not_drain_evidence(self):
        rpc=Mock()
        rpc.block_number.return_value=100000
        rpc.total_supply.return_value=1000
        rpc.is_infra.return_value=True
        with patch("memehunter.forensics._reconstruct",return_value=({"0x"+"c"*40:1000},1000)):
            self.assertFalse(rug_scan(rpc,"0x"+"b"*40,"0x"+"a"*40,120).rug_flags)

    def test_rpc_failure_does_not_promote_partial_holder_flags(self):
        rpc=Mock();rpc.errors=0;gt=Mock();gt.token_pools_raw.return_value=[]
        from memehunter.forensics import ForensicGrade
        def partial(*args):
            rpc.errors+=1
            return ForensicGrade(scanned=True,rug_flags=["untrusted partial flag"])
        with patch("memehunter.forensics.rug_scan",side_effect=partial):
            g=grade(pool(),gt,rpc)
        self.assertFalse(g.rug_flags)
        self.assertFalse(g.scanned)
        self.assertEqual(g.risk_status,"rpc_incomplete")

    def test_collect_retains_old_trending_and_tracks_dropped_pool(self):
        h=Hunter.__new__(Hunter); h.gt=Mock(); h._track_cursor=0
        old=pool(1000); new=pool(5,address="0x"+"d"*40)
        tracked=pool(2000,address="0x"+"e"*40)
        h.gt.new_pools.return_value=[new]; h.gt.trending_pools.return_value=[old]
        h.gt.pool.return_value=tracked
        import time
        h.state=Mock(tracked={tracked.address:time.time()})
        rows=h._collect()
        self.assertIn("trending",rows[old.address].discovery_sources)
        self.assertIn("tracked",rows[tracked.address].discovery_sources)

    def test_archive_preserves_rejects_raw_requests_and_missing_candidates(self):
        p=pool(liquidity_usd=1); v=evaluate(p,Thresholds())
        skipped=pool(500,address="0x"+"d"*40)
        with tempfile.TemporaryDirectory() as d:
            path=archive_cycle({p.address:p,skipped.address:skipped},[v],[{"ok":False}],{},Path(d))
            data=json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["candidates"][0]["decision"]["rejected"])
            self.assertEqual(data["candidates"][1]["decision"]["excluded"],"outside_new_pool_window")
            self.assertFalse(data["requests"][0]["ok"])

    def test_feed_utf8_and_identity_fields(self):
        p=pool();v=evaluate(p,Thresholds())
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"feed.json"
            write_feed([v],[v],{},path=f)
            write_feed([v],[],{},path=f)
            data=json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual(data["alerts"][0]["name"],"猫")
            self.assertEqual(data["board"][0]["quote_address"],p.quote_address)
            self.assertIn("rules_version",data)

    def test_state_tracks_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"state.json"; s=State(f)
            s.tracked={"0xabc":123};s.save()
            self.assertEqual(State(f).tracked,s.tracked)

    def test_scan_never_enables_telegram(self):
        from memehunter.__main__ import cmd_scan
        with patch("memehunter.__main__.GeckoTerminal") as gt, patch("memehunter.__main__.Notifier") as notifier:
            gt.return_value.new_pools.return_value=[]
            gt.return_value.trending_pools.return_value=[pool(1000)]
            cmd_scan()
            notifier.assert_called_once_with(telegram=False)


if __name__=="__main__":unittest.main()
