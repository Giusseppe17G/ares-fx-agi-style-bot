#ifndef AGI_NATIVE_RISK_GATE_MQH
#define AGI_NATIVE_RISK_GATE_MQH
#include <Contracts/RiskContract.mqh>

// Pure, isolated risk gate. It reads no terminal, account, symbol, clock,
// file or network state; every input is supplied by the caller. A decision is
// evidence only and can never release execution.

// Prices, tick sizes, tick values and volumes are compared on an exact decimal
// lattice of 1e-8 so lot flooring matches the Python Decimal reference.
const double NATIVE_RISK_UNIT_SCALE=100000000.0;
// Below 1e6 one double ulp is far smaller than 1e-8, so a lattice member has
// a unique shortest decimal form and its units stay below 2^53.
const double NATIVE_RISK_MAX_LATTICE_VALUE=1000000.0;
const long NATIVE_RISK_EXACT_INTEGER_LIMIT=9007199254740992;
// Same absolute tolerance the Python sizer and gate use for risk comparisons.
const double NATIVE_RISK_COMPARISON_TOLERANCE=1.0e-9;

void NativeRiskClear(NativeRiskDecision &decision)
  {
   decision.accepted=false;
   decision.reject_code="";
   decision.version=NATIVE_RISK_GATE_VERSION;
   decision.approved_lot=0.0;
   decision.risk_amount=0.0;
   decision.risk_pct=0.0;
   decision.open_risk_pct_after=0.0;
   decision.daily_drawdown_pct=0.0;
   decision.floating_drawdown_pct=0.0;
   decision.execution_authorized=false;
   decision.full_pipeline_verified=false;
  }

bool NativeRiskReject(NativeRiskDecision &decision,const string code,const double daily_drawdown_pct,
                      const double floating_drawdown_pct,const double open_risk_pct_after)
  {
   NativeRiskClear(decision);
   decision.reject_code=code;
   decision.daily_drawdown_pct=daily_drawdown_pct;
   decision.floating_drawdown_pct=floating_drawdown_pct;
   decision.open_risk_pct_after=open_risk_pct_after;
   return false;
  }

bool NativeRiskPositiveFinite(const double value)
  {
   return MathIsValidNumber(value) && value>0.0;
  }

// True only when value is the double nearest to units/1e8, i.e. an exact
// lattice member whose shortest decimal form is units/1e8.
bool NativeRiskLatticeUnits(const double value,long &units)
  {
   units=0;
   if(!MathIsValidNumber(value) || value<0.0 || value>NATIVE_RISK_MAX_LATTICE_VALUE) return false;
   long candidate=(long)MathRound(value*NATIVE_RISK_UNIT_SCALE);
   if((double)candidate/NATIVE_RISK_UNIT_SCALE!=value) return false;
   units=candidate;
   return true;
  }

// Largest lattice units not above the decimal value Python reads from repr().
// A non-lattice double cannot have a lattice point between its shortest
// decimal form and its exact binary value, so rounded comparisons are exact.
bool NativeRiskFloorUnits(const double value,long &units)
  {
   units=0;
   if(!MathIsValidNumber(value) || value<0.0 || value>NATIVE_RISK_MAX_LATTICE_VALUE) return false;
   long exact=0;
   if(NativeRiskLatticeUnits(value,exact)) { units=exact; return true; }
   long candidate=(long)MathFloor(value*NATIVE_RISK_UNIT_SCALE);
   while(candidate>0 && (double)candidate/NATIVE_RISK_UNIT_SCALE>value) candidate--;
   while((double)(candidate+1)/NATIVE_RISK_UNIT_SCALE<value) candidate++;
   units=candidate;
   return true;
  }

// Mirrors position_sizer.normalize_lot_down: floor to min+k*step, never above max.
double NativeRiskNormalizeLotDown(const double lot,const long min_units,const long max_units,const long step_units)
  {
   if(!MathIsValidNumber(lot) || lot<=0.0 || min_units<=0 || step_units<=0 || max_units<min_units) return 0.0;
   long bounded=0;
   if(lot>=(double)max_units/NATIVE_RISK_UNIT_SCALE) bounded=max_units;
   else if(!NativeRiskFloorUnits(lot,bounded)) return 0.0;
   if(bounded<min_units) return 0.0;
   long normalized=min_units+((bounded-min_units)/step_units)*step_units;
   if(normalized<min_units || normalized>max_units) return 0.0;
   return (double)normalized/NATIVE_RISK_UNIT_SCALE;
  }

// Account-currency risk of one lot from entry to SL, both on the tick grid.
// A lattice tick value reproduces the exact decimal product of the Python
// reference; otherwise the binary product may differ by one double ulp.
bool NativeRiskPerLot(const double entry,const double sl,const double tick_size,
                      const double tick_value,double &risk_per_lot)
  {
   risk_per_lot=0.0;
   long entry_units=0,sl_units=0,tick_units=0,value_units=0;
   if(!NativeRiskLatticeUnits(entry,entry_units) || !NativeRiskLatticeUnits(sl,sl_units) ||
      !NativeRiskLatticeUnits(tick_size,tick_units) || tick_units<=0 ||
      !NativeRiskPositiveFinite(tick_value)) return false;
   if(entry_units%tick_units!=0 || sl_units%tick_units!=0) return false;
   long distance=entry_units-sl_units;
   if(distance<0) distance=-distance;
   if(distance==0) return false;
   long ticks=distance/tick_units;
   if(NativeRiskLatticeUnits(tick_value,value_units) && value_units>0 &&
      ticks<=NATIVE_RISK_EXACT_INTEGER_LIMIT/value_units)
      risk_per_lot=(double)(ticks*value_units)/NATIVE_RISK_UNIT_SCALE;
   else
      risk_per_lot=(double)ticks*tick_value;
   return NativeRiskPositiveFinite(risk_per_lot);
  }

bool NativeRiskLimitsValid(const NativeRiskLimits &limits)
  {
   return limits.demo_only && !limits.live_trading_approved &&
          NativeRiskPositiveFinite(limits.max_risk_per_trade_pct) && limits.max_risk_per_trade_pct<=0.5 &&
          NativeRiskPositiveFinite(limits.max_open_risk_pct) && limits.max_open_risk_pct<=5.0 &&
          limits.max_open_trades>=1 && limits.max_open_trades<=10 &&
          limits.max_open_trades_per_symbol>=1 && limits.max_open_trades_per_symbol<=limits.max_open_trades &&
          NativeRiskPositiveFinite(limits.max_daily_drawdown_pct) && limits.max_daily_drawdown_pct<=3.0 &&
          NativeRiskPositiveFinite(limits.max_floating_drawdown_pct) && limits.max_floating_drawdown_pct<=5.0 &&
          NativeRiskPositiveFinite(limits.max_spread_points) && limits.max_spread_points<=25.0 &&
          limits.max_signal_age_seconds>=1 && limits.max_signal_age_seconds<=30 &&
          limits.max_snapshot_age_seconds>=1 && limits.max_snapshot_age_seconds<=5 &&
          limits.max_consecutive_losses>=1;
  }

// Snapshot and signal geometry. Python validates the same conditions except
// the native-only finiteness, lattice and tick-grid requirements.
bool NativeRiskMarketValid(const MarketSnapshot &snapshot,const NativeRiskSignal &signal,
                           long &min_units,long &max_units,long &step_units)
  {
   min_units=0; max_units=0; step_units=0;
   long tick_units=0,bid_units=0,ask_units=0;
   if(snapshot.symbol=="" || !NativeRiskPositiveFinite(snapshot.bid) || !NativeRiskPositiveFinite(snapshot.ask) ||
      snapshot.ask<snapshot.bid || !MathIsValidNumber(snapshot.spread_points) || snapshot.spread_points<0.0 ||
      !NativeRiskPositiveFinite(snapshot.point) || !NativeRiskPositiveFinite(snapshot.tick_value) ||
      !NativeRiskPositiveFinite(snapshot.tick_size) || snapshot.stops_level_points<0 || snapshot.freeze_level_points<0)
      return false;
   if(!NativeRiskLatticeUnits(snapshot.volume_min,min_units) || !NativeRiskLatticeUnits(snapshot.volume_max,max_units) ||
      !NativeRiskLatticeUnits(snapshot.volume_step,step_units) || min_units<=0 || step_units<=0 || min_units>max_units)
      return false;
   if(!NativeRiskLatticeUnits(snapshot.tick_size,tick_units) || tick_units<=0 ||
      !NativeRiskLatticeUnits(snapshot.bid,bid_units) || !NativeRiskLatticeUnits(snapshot.ask,ask_units) ||
      bid_units%tick_units!=0 || ask_units%tick_units!=0)
      return false;
   if(signal.symbol!=snapshot.symbol || !MathIsValidNumber(signal.confidence) ||
      signal.confidence<0.0 || signal.confidence>1.0 ||
      !NativeRiskPositiveFinite(signal.sl_price) || !NativeRiskPositiveFinite(signal.tp_price))
      return false;
   long sl_units=0,tp_units=0;
   if(!NativeRiskLatticeUnits(signal.sl_price,sl_units) || !NativeRiskLatticeUnits(signal.tp_price,tp_units) ||
      sl_units%tick_units!=0 || tp_units%tick_units!=0)
      return false;
   double minimum_distance=(double)snapshot.stops_level_points*snapshot.point;
   if(signal.direction==NATIVE_RISK_BUY)
     {
      if(!(signal.sl_price<snapshot.ask && snapshot.ask<signal.tp_price)) return false;
      if(minimum_distance>0.0 && (signal.sl_price>snapshot.bid-minimum_distance ||
                                  signal.tp_price<snapshot.bid+minimum_distance)) return false;
      return true;
     }
   if(signal.direction==NATIVE_RISK_SELL)
     {
      if(!(signal.tp_price<snapshot.bid && snapshot.bid<signal.sl_price)) return false;
      if(minimum_distance>0.0 && (signal.sl_price<snapshot.ask+minimum_distance ||
                                  signal.tp_price>snapshot.ask-minimum_distance)) return false;
      return true;
     }
   return false;
  }

// Evaluates one market-entry candidate in the same order as the Python
// RiskEngine. Returns decision.accepted; a rejection clears every amount.
bool NativeEvaluateRisk(const NativeRiskLimits &limits,const NativeRiskAccount &account,
                        const MarketSnapshot &snapshot,const NativeRiskSignal &signal,
                        const NativeRiskPosition &positions[],const NativeRiskState &state,
                        NativeRiskDecision &decision)
  {
   NativeRiskClear(decision);
   if(!NativeRiskLimitsValid(limits)) return NativeRiskReject(decision,"RISK_LIMITS_INVALID",0.0,0.0,0.0);
   if(state.now_utc_msc<=0 || state.consecutive_losses<0)
      return NativeRiskReject(decision,"RISK_STATE_INVALID",0.0,0.0,0.0);
   if(!account.known) return NativeRiskReject(decision,"ACCOUNT_TYPE_UNKNOWN",0.0,0.0,0.0);
   if(!account.is_demo) return NativeRiskReject(decision,"DEMO_ONLY_REAL_ACCOUNT",0.0,0.0,0.0);
   if(!account.trade_allowed) return NativeRiskReject(decision,"ACCOUNT_TRADE_DISABLED",0.0,0.0,0.0);
   if(!NativeRiskPositiveFinite(account.equity) || !NativeRiskPositiveFinite(account.balance))
      return NativeRiskReject(decision,"RISK_CALCULATION_UNCERTAIN",0.0,0.0,0.0);
   if(state.kill_switch_active && (state.kill_switch_until_utc_msc<=0 || state.now_utc_msc<state.kill_switch_until_utc_msc))
      return NativeRiskReject(decision,"EMERGENCY_KILL_SWITCH",0.0,0.0,0.0);
   if(!state.symbol_allowed) return NativeRiskReject(decision,"SYMBOL_NOT_ALLOWED",0.0,0.0,0.0);
   if(signal.symbol!=snapshot.symbol) return NativeRiskReject(decision,"MARKET_DATA_INVALID",0.0,0.0,0.0);
   long signal_age=state.now_utc_msc-signal.created_at_utc_msc;
   if(signal.created_at_utc_msc<=0 || signal_age<0 || signal_age>(long)limits.max_signal_age_seconds*1000)
      return NativeRiskReject(decision,"STALE_SIGNAL",0.0,0.0,0.0);
   long snapshot_age=state.now_utc_msc-snapshot.timestamp_utc_msc;
   if(snapshot.timestamp_utc_msc<=0 || snapshot_age<0 || snapshot_age>(long)limits.max_snapshot_age_seconds*1000)
      return NativeRiskReject(decision,"MARKET_DATA_INVALID",0.0,0.0,0.0);
   long min_units=0,max_units=0,step_units=0;
   if(!NativeRiskMarketValid(snapshot,signal,min_units,max_units,step_units))
     {
      // Python labels any market/signal failure by the first missing level.
      string code=signal.sl_price==0.0 ? "MISSING_SL" : signal.tp_price==0.0 ? "MISSING_TP" : "MARKET_DATA_INVALID";
      return NativeRiskReject(decision,code,0.0,0.0,0.0);
     }
   if(!state.audit_confirmed) return NativeRiskReject(decision,"INTERNAL_ERROR",0.0,0.0,0.0);
   if(snapshot.spread_points>limits.max_spread_points) return NativeRiskReject(decision,"HIGH_SPREAD",0.0,0.0,0.0);
   if(!state.has_daily_equity_reference || !NativeRiskPositiveFinite(state.daily_equity_reference))
      return NativeRiskReject(decision,"DAILY_DRAWDOWN_REFERENCE_MISSING",0.0,0.0,0.0);
   double daily_drawdown=((state.daily_equity_reference-account.equity)/state.daily_equity_reference)*100.0;
   if(!(daily_drawdown>0.0)) daily_drawdown=0.0;
   if(daily_drawdown>=limits.max_daily_drawdown_pct)
      return NativeRiskReject(decision,"DAILY_DRAWDOWN_LIMIT",daily_drawdown,0.0,0.0);
   // Python uses `reference or balance`: a missing or zero reference means balance.
   double floating_reference=(state.has_floating_drawdown_reference && state.floating_drawdown_reference!=0.0) ?
                             state.floating_drawdown_reference : account.balance;
   if(!NativeRiskPositiveFinite(floating_reference))
      return NativeRiskReject(decision,"RISK_CALCULATION_UNCERTAIN",0.0,0.0,0.0);
   double floating_drawdown=((floating_reference-account.equity)/floating_reference)*100.0;
   if(!(floating_drawdown>0.0)) floating_drawdown=0.0;
   if(floating_drawdown>=limits.max_floating_drawdown_pct)
      return NativeRiskReject(decision,"FLOATING_DRAWDOWN_LIMIT",daily_drawdown,floating_drawdown,0.0);
   if(state.consecutive_losses>=limits.max_consecutive_losses)
      return NativeRiskReject(decision,"CONSECUTIVE_LOSS_LIMIT",0.0,0.0,0.0);
   if(state.cooldown_until_utc_msc>0 && state.now_utc_msc<state.cooldown_until_utc_msc)
      return NativeRiskReject(decision,"COOLDOWN_ACTIVE",0.0,0.0,0.0);
   double candidate_pct=limits.max_risk_per_trade_pct;
   if(signal.has_risk_pct)
     {
      if(!MathIsValidNumber(signal.risk_pct) || signal.risk_pct<=0.0)
         return NativeRiskReject(decision,"RISK_CALCULATION_UNCERTAIN",0.0,0.0,0.0);
      candidate_pct=MathMin(signal.risk_pct,limits.max_risk_per_trade_pct);
     }
   double reference=signal.direction==NATIVE_RISK_BUY ? snapshot.ask : snapshot.bid;
   double risk_per_lot=0.0;
   if(!NativeRiskPerLot(reference,signal.sl_price,snapshot.tick_size,snapshot.tick_value,risk_per_lot))
      return NativeRiskReject(decision,"INVALID_LOT",daily_drawdown,floating_drawdown,0.0);
   double max_risk_amount=account.equity*(candidate_pct/100.0);
   double lot=NativeRiskNormalizeLotDown(max_risk_amount/risk_per_lot,min_units,max_units,step_units);
   if(signal.has_requested_lot)
     {
      double requested=NativeRiskNormalizeLotDown(signal.requested_lot,min_units,max_units,step_units);
      if(requested<=0.0) return NativeRiskReject(decision,"INVALID_LOT",daily_drawdown,floating_drawdown,0.0);
      lot=MathMin(requested,lot);
     }
   if(lot<=0.0) return NativeRiskReject(decision,"INVALID_LOT",daily_drawdown,floating_drawdown,0.0);
   double risk_amount=risk_per_lot*lot;
   if(!NativeRiskPositiveFinite(risk_amount) || risk_amount>max_risk_amount+NATIVE_RISK_COMPARISON_TOLERANCE)
      return NativeRiskReject(decision,"INVALID_LOT",daily_drawdown,floating_drawdown,0.0);
   double risk_pct=(risk_amount/account.equity)*100.0;
   if(risk_pct>limits.max_risk_per_trade_pct+NATIVE_RISK_COMPARISON_TOLERANCE)
      return NativeRiskReject(decision,"MAX_RISK_PER_TRADE",daily_drawdown,floating_drawdown,0.0);
   int count=ArraySize(positions);
   if(count+1>limits.max_open_trades)
      return NativeRiskReject(decision,"MAX_OPEN_TRADES",daily_drawdown,floating_drawdown,0.0);
   int same_symbol=0;
   for(int i=0;i<count;i++)
      if(positions[i].symbol==signal.symbol) same_symbol++;
   if(same_symbol+1>limits.max_open_trades_per_symbol)
      return NativeRiskReject(decision,"MAX_OPEN_TRADES_PER_SYMBOL",daily_drawdown,floating_drawdown,0.0);
   double open_risk_before=0.0;
   for(int i=0;i<count;i++)
     {
      double amount=0.0;
      if(positions[i].has_risk_amount) amount=positions[i].risk_amount;
      else
        {
         double position_risk_per_lot=0.0;
         if(positions[i].symbol=="" || !NativeRiskPositiveFinite(positions[i].volume) ||
            !NativeRiskPerLot(positions[i].entry_price,positions[i].sl_price,positions[i].tick_size,
                              positions[i].tick_value,position_risk_per_lot))
            return NativeRiskReject(decision,"RISK_CALCULATION_UNCERTAIN",daily_drawdown,floating_drawdown,0.0);
         amount=position_risk_per_lot*positions[i].volume;
        }
      if(!MathIsValidNumber(amount) || amount<0.0)
         return NativeRiskReject(decision,"RISK_CALCULATION_UNCERTAIN",daily_drawdown,floating_drawdown,0.0);
      open_risk_before+=amount;
     }
   double open_risk_pct_after=((open_risk_before+risk_amount)/account.equity)*100.0;
   if(!MathIsValidNumber(open_risk_pct_after))
      return NativeRiskReject(decision,"RISK_CALCULATION_UNCERTAIN",daily_drawdown,floating_drawdown,0.0);
   if(open_risk_pct_after>limits.max_open_risk_pct)
      return NativeRiskReject(decision,"MAX_OPEN_RISK",daily_drawdown,floating_drawdown,open_risk_pct_after);
   decision.accepted=true;
   decision.reject_code="";
   decision.approved_lot=lot;
   decision.risk_amount=risk_amount;
   decision.risk_pct=risk_pct;
   decision.open_risk_pct_after=open_risk_pct_after;
   decision.daily_drawdown_pct=daily_drawdown;
   decision.floating_drawdown_pct=floating_drawdown;
   decision.execution_authorized=false;
   decision.full_pipeline_verified=false;
   return true;
  }
#endif
