#ifndef AGI_NATIVE_RISK_CONTRACT_MQH
#define AGI_NATIVE_RISK_CONTRACT_MQH
#include <Contracts/MarketSnapshot.mqh>

const string NATIVE_RISK_GATE_VERSION="native_risk_gate_v1";
const int NATIVE_RISK_BUY=1;
const int NATIVE_RISK_SELL=-1;

// Every limit is explicit; there is no inferred default. Ceilings follow
// PROJECT_SPEC section 6 and can only be made stricter.
struct NativeRiskLimits
  {
   bool demo_only;
   bool live_trading_approved;
   double max_risk_per_trade_pct;
   double max_open_risk_pct;
   int max_open_trades;
   int max_open_trades_per_symbol;
   double max_daily_drawdown_pct;
   double max_floating_drawdown_pct;
   double max_spread_points;
   int max_signal_age_seconds;
   int max_snapshot_age_seconds;
   int max_consecutive_losses;
  };

// known=false means the account type or identity could not be read.
// No login, server, name or credential is part of this contract.
struct NativeRiskAccount
  {
   bool known;
   bool is_demo;
   bool trade_allowed;
   double balance;
   double equity;
  };

// Market entries only. has_* flags distinguish an omitted optional value
// from a supplied zero; an omitted risk_pct means the per-trade limit.
struct NativeRiskSignal
  {
   string symbol;
   int direction;
   long created_at_utc_msc;
   double sl_price;
   double tp_price;
   double confidence;
   bool has_risk_pct;
   double risk_pct;
   bool has_requested_lot;
   double requested_lot;
  };

// An open position is priced from its own explicit tick metadata unless a
// known risk amount is supplied; the gate never looks up another snapshot.
struct NativeRiskPosition
  {
   string symbol;
   double volume;
   double entry_price;
   double sl_price;
   double tick_size;
   double tick_value;
   bool has_risk_amount;
   double risk_amount;
  };

struct NativeRiskState
  {
   long now_utc_msc;
   bool has_daily_equity_reference;
   double daily_equity_reference;
   bool has_floating_drawdown_reference;
   double floating_drawdown_reference;
   bool audit_confirmed;
   bool symbol_allowed;
   bool kill_switch_active;
   long kill_switch_until_utc_msc;
   int consecutive_losses;
   long cooldown_until_utc_msc;
  };

// A decision is advisory evidence only. accepted=true never releases
// execution: execution_authorized and full_pipeline_verified are always false.
struct NativeRiskDecision
  {
   bool accepted;
   string reject_code;
   string version;
   double approved_lot;
   double risk_amount;
   double risk_pct;
   double open_risk_pct_after;
   double daily_drawdown_pct;
   double floating_drawdown_pct;
   bool execution_authorized;
   bool full_pipeline_verified;
  };
#endif
