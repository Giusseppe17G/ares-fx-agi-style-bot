#ifndef AGI_NATIVE_MARKET_READER_MQH
#define AGI_NATIVE_MARKET_READER_MQH
#include <Core/ObservationPolicy.mqh>

bool NativeReadAccount(string &reason)
  {
   ResetLastError();
   bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   bool connected_ok=(GetLastError()==0);
   if(!connected_ok || !connected) return NativeAccountPolicy(false,false,-1,reason);
   ResetLastError();
   long mode=AccountInfoInteger(ACCOUNT_TRADE_MODE);
   return NativeAccountPolicy(connected,GetLastError()==0,mode,reason);
  }

bool NativeReadSnapshot(const string symbol,const string timeframe,const datetime now_utc,
                        const NativeObservationConfig &config,MarketSnapshot &snapshot,string &reason)
  {
   ZeroMemory(snapshot);
   snapshot.symbol=symbol;
   snapshot.timeframe=timeframe;
   snapshot.observed_at_utc=now_utc;
   long digits=0,stops=0,freeze=0,selected=0;
   if(!SymbolInfoInteger(symbol,SYMBOL_SELECT,selected) || selected==0 || !SymbolIsSynchronized(symbol))
     { reason="SYMBOL_UNAVAILABLE"; return false; }
   // Boolean property overloads distinguish a legitimate zero from read failure.
   if(!SymbolInfoInteger(symbol,SYMBOL_DIGITS,digits) ||
      !SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL,stops) ||
      !SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL,freeze) ||
      !SymbolInfoDouble(symbol,SYMBOL_POINT,snapshot.point) ||
      !SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE,snapshot.tick_size) ||
      !SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE,snapshot.tick_value) ||
      !SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN,snapshot.volume_min) ||
      !SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX,snapshot.volume_max) ||
      !SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP,snapshot.volume_step))
     { reason="MARKET_METADATA_UNAVAILABLE"; return false; }
   if(digits<0 || digits>8 || stops<0 || stops>INT_MAX || freeze<0 || freeze>INT_MAX)
     { reason="MARKET_METADATA_INVALID"; return false; }
   snapshot.digits=(int)digits;
   snapshot.stops_level_points=(int)stops;
   snapshot.freeze_level_points=(int)freeze;
   MqlTick tick={};
   if(!SymbolInfoTick(symbol,tick) || tick.time<=0 || tick.time_msc/1000!=(long)tick.time)
     { reason="TICK_UNAVAILABLE"; return false; }
   snapshot.bid=tick.bid;
   snapshot.ask=tick.ask;
   if(!NativePositive(snapshot.point))
     { reason="MARKET_METADATA_INVALID"; return false; }
   snapshot.spread_points=(tick.ask-tick.bid)/snapshot.point;
   snapshot.source_tick_server_msc=tick.time_msc;
   long utc_msc=0;
   if(!NativeNormalizeTickTime(tick.time_msc,now_utc,config,utc_msc,reason)) return false;
   snapshot.timestamp_utc_msc=utc_msc;
   snapshot.timestamp_utc=(datetime)(utc_msc/1000);
   return NativeValidateSnapshot(snapshot,config,reason);
  }
#endif
