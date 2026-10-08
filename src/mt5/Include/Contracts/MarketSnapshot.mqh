#ifndef AGI_NATIVE_MARKET_SNAPSHOT_MQH
#define AGI_NATIVE_MARKET_SNAPSHOT_MQH

// Native observation schema 1.0. This is not a Python replay input record.
struct MarketSnapshot
  {
   string symbol;
   string timeframe;
   datetime timestamp_utc;
   long timestamp_utc_msc;
   long source_tick_server_msc;
   datetime observed_at_utc;
   double bid;
   double ask;
   double spread_points;
   int digits;
   double point;
   double tick_value;
   double tick_size;
   double volume_min;
   double volume_max;
   double volume_step;
   int stops_level_points;
   int freeze_level_points;
  };

struct NativeObservationConfig
  {
   bool demo_only;
   bool live_trading_approved;
   bool utc_clock_confirmed;
   int server_utc_offset_seconds;
   datetime offset_valid_from_utc;
   datetime offset_valid_until_utc;
   double max_spread_points;
   int max_tick_age_seconds;
   int timer_seconds;
  };
#endif
