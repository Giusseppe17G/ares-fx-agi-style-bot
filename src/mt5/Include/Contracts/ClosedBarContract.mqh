#ifndef AGI_NATIVE_CLOSED_BAR_CONTRACT_MQH
#define AGI_NATIVE_CLOSED_BAR_CONTRACT_MQH

// Canonical UTC milliseconds supplied by the caller; no provenance is inferred.
// Calendar ceiling: 3000-12-31 23:59:59.999 UTC.
const long NATIVE_CLOSED_BAR_MAX_UTC_MSC=32535215999999;

struct NativeClosedBar
  {
   long timestamp_utc_msc;
   double open;
   double high;
   double low;
   double close;
   double volume;
   double spread_points;
  };

struct NativeClosedBarRequest
  {
   string symbol;
   string timeframe;
   long snapshot_utc_msc;
   long clock_start_utc_msc;
   int clock_resolution_msc;
   int minimum_bars;
   int max_snapshot_age_msc;
  };

struct NativeClosedBarResult
  {
   bool valid;
   string reason;
   string timeframe;
   int input_count;
   int closed_count;
   int excluded_count;
   long source_bar_timestamp_utc_msc;
   long available_at_utc_msc;
   bool execution_authorized;
   bool full_pipeline_verified;
   // Owned dynamic output: every rejection releases the previous window.
   NativeClosedBar closed_bars[];
  };
#endif
