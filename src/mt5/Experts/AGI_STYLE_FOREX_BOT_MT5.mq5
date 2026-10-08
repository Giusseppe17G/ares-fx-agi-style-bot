#property strict
#property version "1.000"
#property description "Native observation only. Trading release is permanently blocked."

#include <Core/NativeClock.mqh>
#include <Core/NativeMarketReader.mqh>
#include <Telemetry/JsonlAudit.mqh>
#include <Execution/ReleaseGate.mqh>

input bool DEMO_ONLY=true;
input bool LIVE_TRADING_APPROVED=false;
input bool UTC_CLOCK_CONFIRMED=false;
input int SERVER_UTC_OFFSET_SECONDS=2147483647;
input datetime UTC_OFFSET_VALID_FROM=D'1970.01.01 00:00:00';
input datetime UTC_OFFSET_VALID_UNTIL=D'1970.01.01 00:00:00';
input double MAX_SPREAD_POINTS=25.0;
input int MAX_TICK_AGE_SECONDS=5;
input int OBSERVATION_INTERVAL_SECONDS=1;

NativeObservationConfig observation_config;
NativeUtcClock observation_clock;
NativeJsonlAudit observation_audit;
bool observation_active=false;
datetime last_observed_utc=0;

int ObservationInitFailure(const string reason)
  {
   observation_audit.Append(last_observed_utc,"NATIVE_INIT_REJECTED","CRITICAL",_Symbol,reason);
   observation_audit.Close();
   Print("NATIVE_OBSERVATION_ONLY: initialization rejected: ",reason,"; release remains BLOCKED.");
   return INIT_FAILED;
  }

int OnInit(void)
  {
   // Auditing is established before any account or market observation.
   if(!observation_audit.Open())
     { Print("NATIVE_AUDIT_UNAVAILABLE: initialization rejected."); return INIT_FAILED; }
   string reason="";
   if(!observation_clock.Read(last_observed_utc,reason)) return ObservationInitFailure(reason);
   observation_config.demo_only=DEMO_ONLY;
   observation_config.live_trading_approved=LIVE_TRADING_APPROVED;
   observation_config.utc_clock_confirmed=UTC_CLOCK_CONFIRMED;
   observation_config.server_utc_offset_seconds=SERVER_UTC_OFFSET_SECONDS;
   observation_config.offset_valid_from_utc=UTC_OFFSET_VALID_FROM;
   observation_config.offset_valid_until_utc=UTC_OFFSET_VALID_UNTIL;
   observation_config.max_spread_points=MAX_SPREAD_POINTS;
   observation_config.max_tick_age_seconds=MAX_TICK_AGE_SECONDS;
   observation_config.timer_seconds=OBSERVATION_INTERVAL_SECONDS;
   if(!NativeValidateConfig(observation_config,reason)) return ObservationInitFailure(reason);
   if(last_observed_utc<UTC_OFFSET_VALID_FROM || last_observed_utc>=UTC_OFFSET_VALID_UNTIL)
      return ObservationInitFailure("UTC_OFFSET_WINDOW_INVALID");
   if(!NativeReadAccount(reason)) return ObservationInitFailure(reason);
   observation_audit.SetDemoVerified();
   NativeExecutionGate(reason);
   string policy="{\"server_utc_offset_seconds\":"+IntegerToString(SERVER_UTC_OFFSET_SECONDS)+
      ",\"offset_valid_from_utc\":"+NativeUtcJson(UTC_OFFSET_VALID_FROM)+
      ",\"offset_valid_until_utc\":"+NativeUtcJson(UTC_OFFSET_VALID_UNTIL)+
      ",\"utc_clock_confirmed\":true,\"clock_source\":\"HOST_COMPUTED_TIMEGMT\",\"clock_resolution_ms\":1000,"+
      "\"max_spread_points\":"+DoubleToString(MAX_SPREAD_POINTS,8)+
      ",\"max_tick_age_seconds\":"+IntegerToString(MAX_TICK_AGE_SECONDS)+
      ",\"demo_only_input\":"+(DEMO_ONLY ? "true" : "false")+
      ",\"live_trading_approved_input\":"+(LIVE_TRADING_APPROVED ? "true" : "false")+"}";
   if(!observation_audit.Append(last_observed_utc,"NATIVE_OBSERVER_STARTED","INFO",_Symbol,reason,policy))
      return ObservationInitFailure("AUDIT_PERSISTENCE_FAILED");
   if(!EventSetTimer(OBSERVATION_INTERVAL_SECONDS)) return ObservationInitFailure("TIMER_UNAVAILABLE");
   observation_active=true;
   return INIT_SUCCEEDED;
  }

void ObservationHalt(const string reason)
  {
   observation_active=false;
   EventKillTimer();
   if(!observation_audit.Append(last_observed_utc,"NATIVE_OBSERVER_HALTED","CRITICAL",_Symbol,reason))
      Print("NATIVE_AUDIT_FAILED: observation stopped; release remains BLOCKED.");
   ExpertRemove();
  }

void OnTimer(void)
  {
   if(!observation_active) return;
   string reason="";
   datetime now_utc=0;
   if(!observation_clock.Read(now_utc,reason))
     { last_observed_utc=0; observation_audit.SetDemoVerified(false); ObservationHalt(reason); return; }
   last_observed_utc=now_utc;
   if(!NativeReadAccount(reason))
     { observation_audit.SetDemoVerified(false); ObservationHalt(reason); return; }
   MarketSnapshot snapshot={};
   if(!NativeReadSnapshot(_Symbol,EnumToString(_Period),now_utc,observation_config,snapshot,reason))
     {
      if(!observation_audit.Append(now_utc,"MARKET_OBSERVATION_REJECTED","WARNING",_Symbol,reason))
         ObservationHalt("AUDIT_PERSISTENCE_FAILED");
      return;
     }
   string block_reason="";
   NativeExecutionGate(block_reason);
   string payload="{\"observation_valid\":true,\"execution_reject_code\":"+NativeJsonString(block_reason)+
                  ",\"snapshot\":"+NativeSnapshotJson(snapshot)+"}";
   if(!observation_audit.Append(now_utc,"MARKET_OBSERVATION_ACCEPTED","INFO",_Symbol,reason,payload))
      ObservationHalt("AUDIT_PERSISTENCE_FAILED");
  }

void OnDeinit(const int reason)
  {
   observation_active=false;
   EventKillTimer();
   if(observation_audit.Healthy())
      if(!observation_audit.Append(last_observed_utc,"NATIVE_OBSERVER_STOPPED","INFO",_Symbol,"OBSERVER_STOPPED",
                                  "{\"deinit_reason\":"+IntegerToString(reason)+"}"))
         Print("NATIVE_AUDIT_FAILED: final observation event was not confirmed.");
   observation_audit.Close();
  }
