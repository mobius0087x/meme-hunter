import copy, unittest
from replay import replay, aggregate, cohort, validate_bar

S={'pool':'0xpool','token':'0xtoken','symbol':'TEST','ts':1,'available_ts':61,'tier':'ALERT'}
def data():
    return {'pool':'0xpool','token':'0xtoken','currency':'usd','interval_s':60,
       'source_url':'synthetic-unit-test-only','fetched_at':'2026-09-07T00:00:00Z',
       'rows':[[t,1,1.01,.99,1,100000] for t in range(0,600,60)]}

class ReplayTests(unittest.TestCase):
    def test_no_lookahead(self):
        r=replay(S,data(),horizon_s=120)
        self.assertEqual(r['entry_ts'],180);self.assertEqual(r['exit_ts'],300)
        self.assertEqual(r['status'],'priced_proxy')
        self.assertAlmostEqual(r['net_return'],.98*.98-1)
    def test_missing_keeps_denominator(self):
        rows=[replay(S,None),replay(S,data(),horizon_s=120)]
        a=aggregate(rows);self.assertEqual(a['eligible'],2);self.assertEqual(a['coverage'],.5)
        self.assertIsNone(a['unconditional_mean_return'])
    def test_identity(self):
        d=data();d['token']='0xother';self.assertEqual(replay(S,d)['status'],'identity_mismatch')
    def test_gap_not_forward_filled(self):
        d=data();d['rows']=[r for r in d['rows'] if r[0]!=240]
        self.assertEqual(replay(S,d,horizon_s=120)['status'],'censored_missing_bar_after_entry')
    def test_stop_before_target_when_ambiguous(self):
        d=data();d['rows'][3]=[180,1,1.5,.7,1,100000]
        r=replay(S,d,horizon_s=120);self.assertEqual(r['exit_reason'],'stop');self.assertTrue(r['intrabar_ambiguous']);self.assertEqual(r['exit_price'],.8)
    def test_gap_stop_worse_than_stop(self):
        d=data();d['rows'][4]=[240,.5,.6,.4,.5,100000]
        r=replay(S,d,horizon_s=120);self.assertEqual(r['exit_price'],.5)
    def test_quiet_holding_bar_is_not_missing(self):
        d=data();d['rows'][4][-1]=0
        r=replay(S,d,horizon_s=120);self.assertEqual(r['status'],'priced_proxy');self.assertEqual(r['quiet_bars'],1)
    def test_zero_volume_exit_unknown(self):
        d=data();d['rows'][5][-1]=0
        self.assertEqual(replay(S,d,horizon_s=120)['status'],'censored_time_exit_no_trades')
    def test_future_volume_cannot_rescue_entry(self):
        d=data();d['rows'][2][-1]=1
        self.assertEqual(replay(S,d,horizon_s=120)['status'],'entry_capacity_rejected')
    def test_invalid_wick_quarantined(self):
        d=data();d['rows'][3][2]=1e12
        self.assertEqual(replay(S,d,horizon_s=120)['status'],'suspect_wick_requires_review')
    def test_token_dedup(self):
        other={**S,'pool':'0xpool2','available_ts':90}
        self.assertEqual(len(cohort([other,S])),1)
    def test_duplicate_candles_rejected(self):
        d=data();d['rows'].append(d['rows'][0])
        self.assertEqual(replay(S,d)['status'],'duplicate_timestamp')
    def test_tax_stress_is_monotonic(self):
        a=replay(S,data(),horizon_s=120,cost_bps=50);b=replay(S,data(),horizon_s=120,cost_bps=500)
        self.assertGreater(a['net_return'],b['net_return'])
    def test_misaligned_timestamp_rejected(self):
        d=data();d['rows'][0][0]=1
        self.assertEqual(replay(S,d)['status'],'unaligned_timestamp')
    def test_optimistic_ambiguity_is_explicit(self):
        d=data();d['rows'][3]=[180,1,1.5,.7,1,100000]
        r=replay(S,d,horizon_s=120,intrabar_policy='target_first')
        self.assertTrue(r['intrabar_ambiguous']);self.assertEqual(r['exit_price'],1.4)

if __name__=='__main__':unittest.main()
