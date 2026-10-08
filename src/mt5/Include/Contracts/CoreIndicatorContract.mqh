#ifndef AGI_NATIVE_CORE_INDICATOR_CONTRACT_MQH
#define AGI_NATIVE_CORE_INDICATOR_CONTRACT_MQH

const string NATIVE_CORE_INDICATOR_VERSION="native_core_indicators_v1";

// Scalar observation only. Numeric zero on a rejected result means unavailable;
// callers must check valid. No field can release execution or certify parity.
struct NativeCoreIndicatorResult
  {
   bool valid;
   string reason;
   string version;
   string symbol;
   string timeframe;
   int bars_count;
   long history_start_utc_msc;
   long source_bar_timestamp_utc_msc;
   long available_at_utc_msc;
   long snapshot_utc_msc;
   long clock_start_utc_msc;
   int clock_resolution_msc;
   double ema20;
   double ema50;
   double ema200;
   double rsi14;
   double atr14;
   bool execution_authorized;
   bool full_pipeline_verified;
  };
#endif
