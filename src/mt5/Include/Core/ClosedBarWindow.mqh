#ifndef AGI_NATIVE_CLOSED_BAR_WINDOW_MQH
#define AGI_NATIVE_CLOSED_BAR_WINDOW_MQH
#include <Contracts/ClosedBarContract.mqh>

// Explicit adapter only. The selector itself requires a canonical timeframe.
bool NativeNormalizeClosedBarTimeframe(const string raw,string &canonical)
  {
   string raw_value=raw;
   canonical="";
   if(raw_value=="M5" || raw_value=="PERIOD_M5") canonical="M5";
   else if(raw_value=="M15" || raw_value=="PERIOD_M15") canonical="M15";
   else if(raw_value=="H1" || raw_value=="PERIOD_H1") canonical="H1";
   return StringLen(canonical)>0;
  }

long NativeClosedBarDurationMsc(const string canonical)
  {
   if(canonical=="M5") return 300000;
   if(canonical=="M15") return 900000;
   if(canonical=="H1") return 3600000;
   return 0;
  }

bool NativeRejectClosedBars(NativeClosedBarResult &result,const string reason)
  {
   ArrayFree(result.closed_bars);
   result.valid=false;
   result.reason=reason;
   result.closed_count=0;
   result.excluded_count=0;
   result.source_bar_timestamp_utc_msc=0;
   result.available_at_utc_msc=0;
   result.execution_authorized=false;
   result.full_pipeline_verified=false;
   return false;
  }

bool NativeClosedBarValuesValid(const NativeClosedBar &bar)
  {
   if(!MathIsValidNumber(bar.open) || !MathIsValidNumber(bar.high) ||
      !MathIsValidNumber(bar.low) || !MathIsValidNumber(bar.close) ||
      !MathIsValidNumber(bar.volume) || !MathIsValidNumber(bar.spread_points)) return false;
   return bar.open>0.0 && bar.high>0.0 && bar.low>0.0 && bar.close>0.0 &&
          bar.high>=bar.low && bar.high>=bar.open && bar.high>=bar.close &&
          bar.low<=bar.open && bar.low<=bar.close && bar.volume>=0.0 && bar.spread_points>=0.0;
  }

// Pure selection only. No acquisition, clocks, account state or authorization.
// All rows are validated, including forming/future rows. Gaps remain unchanged.
bool NativeSelectClosedBars(const NativeClosedBarRequest &request,
                            const NativeClosedBar &bars[],NativeClosedBarResult &result)
  {
   // Snapshot the input before reset: a caller may reuse result.closed_bars as
   // the next input. A local copy prevents clearing it before validation.
   int input_count=ArraySize(bars);
   NativeClosedBar source[];
   if(ArrayResize(source,input_count)!=input_count)
     {
      result.input_count=input_count;
      result.timeframe="";
      return NativeRejectClosedBars(result,"ALLOCATION_FAILED");
     }
   for(int index=0;index<input_count;index++) source[index]=bars[index];
   NativeRejectClosedBars(result,"REQUEST_INVALID");
   result.input_count=input_count;
   result.timeframe="";
   if(ArraySize(result.closed_bars)!=0) return NativeRejectClosedBars(result,"ALLOCATION_FAILED");
   string symbol=request.symbol;
   StringTrimLeft(symbol);
   StringTrimRight(symbol);
   if(StringLen(symbol)==0) return NativeRejectClosedBars(result,"SYMBOL_INVALID");
   long duration=NativeClosedBarDurationMsc(request.timeframe);
   if(duration==0) return NativeRejectClosedBars(result,"TIMEFRAME_INVALID");
   result.timeframe=request.timeframe;
   if(request.minimum_bars<=0 || request.max_snapshot_age_msc<=0 || request.max_snapshot_age_msc>5000 ||
      (request.clock_resolution_msc!=1 && request.clock_resolution_msc!=1000))
      return NativeRejectClosedBars(result,"REQUEST_LIMITS_INVALID");
   if(request.snapshot_utc_msc<=0 || request.snapshot_utc_msc>NATIVE_CLOSED_BAR_MAX_UTC_MSC ||
      request.clock_start_utc_msc<=0 ||
      request.clock_start_utc_msc>NATIVE_CLOSED_BAR_MAX_UTC_MSC-(request.clock_resolution_msc-1))
      return NativeRejectClosedBars(result,"REQUEST_TIMESTAMP_INVALID");
   // Reject a possibly future snapshot even when inside the observation second.
   if(request.snapshot_utc_msc>request.clock_start_utc_msc)
      return NativeRejectClosedBars(result,"FUTURE_SNAPSHOT");
   long clock_upper=request.clock_start_utc_msc+request.clock_resolution_msc-1;
   if(clock_upper-request.snapshot_utc_msc>request.max_snapshot_age_msc)
      return NativeRejectClosedBars(result,"STALE_SNAPSHOT");
   if(result.input_count==0) return NativeRejectClosedBars(result,"EMPTY_HISTORY");

   long previous_open=0,previous_close=0,latest_available=0;
   int selected_count=0;
   for(int index=0;index<result.input_count;index++)
     {
      long opened=source[index].timestamp_utc_msc;
      if(opened<=0 || opened>NATIVE_CLOSED_BAR_MAX_UTC_MSC-duration)
         return NativeRejectClosedBars(result,"BAR_TIMESTAMP_INVALID");
      if(!NativeClosedBarValuesValid(source[index])) return NativeRejectClosedBars(result,"BAR_VALUES_INVALID");
      if(index>0 && opened<=previous_open) return NativeRejectClosedBars(result,"BAR_TIME_ORDER_INVALID");
      if(index>0 && opened<previous_close) return NativeRejectClosedBars(result,"BAR_INTERVAL_OVERLAP");
      long available=opened+duration;
      if(available<=request.snapshot_utc_msc)
        { selected_count++; latest_available=available; }
      previous_open=opened;
      previous_close=available;
     }
   if(selected_count==0) return NativeRejectClosedBars(result,"NO_CLOSED_BARS");
   if(selected_count<request.minimum_bars) return NativeRejectClosedBars(result,"INSUFFICIENT_CLOSED_BARS");
   if(clock_upper-latest_available>duration+request.max_snapshot_age_msc)
      return NativeRejectClosedBars(result,"STALE_CLOSED_BARS");

   if(ArrayResize(result.closed_bars,selected_count)!=selected_count)
      return NativeRejectClosedBars(result,"ALLOCATION_FAILED");
   // Strict chronological, nonoverlapping input makes the selected set a prefix.
   for(int index=0;index<selected_count;index++) result.closed_bars[index]=source[index];
   result.closed_count=selected_count;
   result.excluded_count=result.input_count-selected_count;
   result.source_bar_timestamp_utc_msc=source[selected_count-1].timestamp_utc_msc;
   result.available_at_utc_msc=latest_available;
   result.reason="CLOSED_BARS_VALID";
   result.valid=true;
   return true;
  }
#endif
