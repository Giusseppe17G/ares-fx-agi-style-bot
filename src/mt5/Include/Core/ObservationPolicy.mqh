#ifndef AGI_NATIVE_OBSERVATION_POLICY_MQH
#define AGI_NATIVE_OBSERVATION_POLICY_MQH
#include <Contracts/MarketSnapshot.mqh>

bool NativePositive(const double value)
  {
   return MathIsValidNumber(value) && value>0.0;
  }

bool NativeOnGrid(const double value,const double step)
  {
   if(!MathIsValidNumber(value) || !NativePositive(step) || value<0.0)
      return false;
   double units=value/step;
   // Bound precision loss; tolerance is one hundred-millionth of a step.
   return MathIsValidNumber(units) && units<1.0e12 &&
          MathAbs(value-MathRound(units)*step)<=step*1.0e-8;
  }

bool NativeVolumeValid(const double lot,const MarketSnapshot &snapshot)
  {
   return NativePositive(lot) && lot>=snapshot.volume_min && lot<=snapshot.volume_max &&
          NativeOnGrid(lot-snapshot.volume_min,snapshot.volume_step);
  }

bool NativeAccountPolicy(const bool connected,const bool read_ok,const long mode,string &reason)
  {
   if(!connected || !read_ok)
     { reason="ACCOUNT_TYPE_UNKNOWN"; return false; }
   if(mode!=ACCOUNT_TRADE_MODE_DEMO && mode!=ACCOUNT_TRADE_MODE_REAL && mode!=ACCOUNT_TRADE_MODE_CONTEST)
     { reason="ACCOUNT_TYPE_UNKNOWN"; return false; }
   // User-facing flags cannot relax this invariant, including on contest accounts.
   if(mode!=ACCOUNT_TRADE_MODE_DEMO)
     { reason="DEMO_ACCOUNT_REQUIRED"; return false; }
   reason="DEMO_ACCOUNT_VERIFIED";
   return true;
  }

bool NativeValidateConfig(const NativeObservationConfig &config,string &reason)
  {
   if(!NativePositive(config.max_spread_points) || config.max_spread_points>25.0 ||
      config.max_tick_age_seconds<=0 || config.max_tick_age_seconds>5 ||
      config.timer_seconds<1 || config.timer_seconds>60)
     { reason="CONFIGURATION_INVALID"; return false; }
   if(!config.utc_clock_confirmed)
     { reason="UTC_CLOCK_UNCONFIRMED"; return false; }
   if(config.server_utc_offset_seconds<-50400 || config.server_utc_offset_seconds>50400 ||
      config.server_utc_offset_seconds%60!=0 || config.offset_valid_from_utc<=0 ||
      config.offset_valid_until_utc<=config.offset_valid_from_utc)
     { reason="SERVER_UTC_OFFSET_UNVERIFIED"; return false; }
   reason="CONFIGURATION_DECLARED";
   return true;
  }

bool NativeNormalizeTickTime(const long server_msc,const datetime now_utc,
                             const NativeObservationConfig &config,long &utc_msc,string &reason)
  {
   utc_msc=0;
   if(!NativeValidateConfig(config,reason)) return false;
   if(now_utc<=0 || now_utc<config.offset_valid_from_utc || now_utc>=config.offset_valid_until_utc)
     { reason="UTC_OFFSET_WINDOW_INVALID"; return false; }
   // datetime's documented calendar range ends at 3000-12-31. Bound arithmetic.
   if(server_msc<=0 || server_msc>32535215999999)
     { reason="TICK_TIME_INVALID"; return false; }
   long normalized=server_msc-(long)config.server_utc_offset_seconds*1000;
   if(normalized<=0 || normalized>32535215999999 ||
      normalized<(long)config.offset_valid_from_utc*1000 ||
      normalized>=(long)config.offset_valid_until_utc*1000)
     { reason="UTC_OFFSET_WINDOW_INVALID"; return false; }
   // TimeGMT has second precision: do not invent a millisecond receipt clock.
   // Use the oldest possible age in the observation second for freshness.
   long upper_now=(long)now_utc*1000+999;
   if(normalized>upper_now)
     { reason="FUTURE_TICK"; return false; }
   if(upper_now-normalized>(long)config.max_tick_age_seconds*1000)
     { reason="STALE_TICK"; return false; }
   utc_msc=normalized;
   reason="TICK_TIME_VALID";
   return true;
  }

bool NativeValidateSnapshot(const MarketSnapshot &s,const NativeObservationConfig &config,string &reason)
  {
   if(!NativeValidateConfig(config,reason)) return false;
   if(StringLen(s.symbol)==0 || StringLen(s.timeframe)==0 ||
      !NativePositive(s.bid) || !NativePositive(s.ask) || s.ask<s.bid ||
      !NativePositive(s.point) || !NativePositive(s.tick_size) || !NativePositive(s.tick_value) ||
      !NativePositive(s.volume_min) || !NativePositive(s.volume_max) || !NativePositive(s.volume_step) ||
      s.volume_min>s.volume_max || s.digits<0 || s.digits>8 ||
      s.stops_level_points<0 || s.freeze_level_points<0)
     { reason="MARKET_METADATA_INVALID"; return false; }
   if(MathAbs(s.point-MathPow(10.0,-s.digits))>s.point*1.0e-8 ||
      !NativeOnGrid(s.tick_size,s.point) || !NativeOnGrid(s.bid,s.tick_size) ||
      !NativeOnGrid(s.ask,s.tick_size) || !NativeVolumeValid(s.volume_max,s))
     { reason="MARKET_GRID_INVALID"; return false; }
   double actual_spread=(s.ask-s.bid)/s.point;
   if(!MathIsValidNumber(s.spread_points) || s.spread_points<0.0 ||
      !MathIsValidNumber(actual_spread) || MathAbs(actual_spread-s.spread_points)>1.0e-6)
     { reason="SPREAD_INVALID"; return false; }
   if(actual_spread>config.max_spread_points+1.0e-8)
     { reason="HIGH_SPREAD"; return false; }
   long normalized=0;
   if(!NativeNormalizeTickTime(s.source_tick_server_msc,s.observed_at_utc,config,normalized,reason)) return false;
   if(s.timestamp_utc_msc!=normalized || s.timestamp_utc!=(datetime)(normalized/1000))
     { reason="TIMESTAMP_MISMATCH"; return false; }
   reason="OBSERVATION_VALID";
   return true;
  }
#endif
