#property strict
#property script_show_inputs
#include <Core/ObservationPolicy.mqh>
#include <Execution/ReleaseGate.mqh>
#include <Telemetry/JsonlAudit.mqh>

// Pure fixture harness: no market/account reads, file writes or trading APIs.
// Compiling this script does not execute the assertions.
int failures=0;
int checks=0;
void Check(const bool condition,const string label)
  {
   checks++;
   if(!condition) { failures++; Print("ASSERTION_FAILED: ",label); }
  }

void OnStart(void)
  {
   string reason="";
   Check(!NativeExecutionGate(reason) && reason=="EXECUTION_NOT_RELEASED","release always blocked");
   Check(NativeAccountPolicy(true,true,ACCOUNT_TRADE_MODE_DEMO,reason),"known demo");
   Check(!NativeAccountPolicy(true,true,ACCOUNT_TRADE_MODE_REAL,reason),"real rejected");
   Check(!NativeAccountPolicy(true,true,ACCOUNT_TRADE_MODE_CONTEST,reason),"contest rejected");
   Check(!NativeAccountPolicy(false,true,ACCOUNT_TRADE_MODE_DEMO,reason),"disconnected unknown");
   Check(!NativeAccountPolicy(true,false,ACCOUNT_TRADE_MODE_DEMO,reason),"failed account read");
   Check(!NativeAccountPolicy(true,true,-1,reason),"unknown account mode");
   NativeObservationConfig cfg={};
   cfg.demo_only=true;
   cfg.live_trading_approved=false;
   cfg.utc_clock_confirmed=true;
   cfg.server_utc_offset_seconds=7200;
   cfg.offset_valid_from_utc=D'2026.10.05 00:00:00';
   cfg.offset_valid_until_utc=D'2026.10.06 00:00:00';
   cfg.max_spread_points=25;
   cfg.max_tick_age_seconds=5;
   cfg.timer_seconds=1;
   Check(NativeValidateConfig(cfg,reason),"explicit configuration");
   cfg.demo_only=false; cfg.live_trading_approved=true;
   Check(!NativeExecutionGate(reason),"flags never release execution");
   Check(!NativeAccountPolicy(true,true,ACCOUNT_TRADE_MODE_REAL,reason),"flags never admit real");
   cfg.utc_clock_confirmed=false;
   Check(!NativeValidateConfig(cfg,reason),"unconfirmed UTC");
   cfg.utc_clock_confirmed=true;
   cfg.server_utc_offset_seconds=2147483647;
   Check(!NativeValidateConfig(cfg,reason),"unknown offset");
   cfg.server_utc_offset_seconds=7200;
   datetime now=D'2026.10.05 12:00:00';
   long raw=((long)now+7200)*1000,normalized=0;
   Check(NativeNormalizeTickTime(raw,now,cfg,normalized,reason) && normalized==(long)now*1000,"explicit normalization");
   Check(!NativeNormalizeTickTime(raw+1000,now,cfg,normalized,reason) && reason=="FUTURE_TICK","future tick");
   Check(!NativeNormalizeTickTime(raw-5000,now,cfg,normalized,reason) && reason=="STALE_TICK","conservative second resolution");
   Check(NativeNormalizeTickTime(raw-4000,now,cfg,normalized,reason),"fresh upper age");
   Check(!NativeNormalizeTickTime(raw,cfg.offset_valid_until_utc,cfg,normalized,reason),"expired offset");
   Check(!NativeNormalizeTickTime(0,now,cfg,normalized,reason),"missing ticktime");
   MarketSnapshot s={};
   s.symbol="EURUSD"; s.timeframe="PERIOD_M5"; s.observed_at_utc=now;
   s.timestamp_utc=now; s.timestamp_utc_msc=(long)now*1000; s.source_tick_server_msc=raw;
   s.bid=1.1000; s.ask=1.1001; s.spread_points=10.0; s.digits=5;
   s.point=0.00001; s.tick_size=0.00001; s.tick_value=1.0;
   s.volume_min=0.01; s.volume_max=100.0; s.volume_step=0.01;
   Check(NativeValidateSnapshot(s,cfg,reason),"valid quote");
   s.ask=1.1003; s.spread_points=30.0;
   Check(!NativeValidateSnapshot(s,cfg,reason) && reason=="HIGH_SPREAD","spread blocks");
   s.ask=1.1001; s.spread_points=10.0; s.bid=1.100001;
   Check(!NativeValidateSnapshot(s,cfg,reason) && reason=="MARKET_GRID_INVALID","offgrid quote");
   s.bid=1.1000; s.tick_value=0.0;
   Check(!NativeValidateSnapshot(s,cfg,reason),"missing tickvalue");
   s.tick_value=1.0; s.spread_points=1.0;
   Check(!NativeValidateSnapshot(s,cfg,reason) && reason=="SPREAD_INVALID","inconsistent spread");
   s.spread_points=10.0; s.timestamp_utc_msc++;
   Check(!NativeValidateSnapshot(s,cfg,reason) && reason=="TIMESTAMP_MISMATCH","timestamp mismatch");
   s.timestamp_utc_msc--; s.volume_min=0.05; s.volume_step=0.1; s.volume_max=1.05;
   Check(NativeVolumeValid(0.15,s),"minimum anchored volume");
   Check(!NativeVolumeValid(0.10,s),"wrong volume lattice");
   Check(!NativeVolumeValid(0.0,s),"zero volume");
   Check(!NativeVolumeValid(1.15,s),"volume above maximum");
   Check(NativeJsonString("x\"\\\n")=="\"x\\\"\\\\\\u000a\"","JSON escape");
   Check(NativeUtcJson(now)=="\"2026-10-05T12:00:00Z\"","UTC formatting");
   Check(NativeUtcJson(0)=="null","missing timestamp not fabricated");
   PrintFormat("NATIVE_POLICY_HARNESS checks=%d failures=%d",checks,failures);
  }
