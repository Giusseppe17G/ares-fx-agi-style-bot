#ifndef AGI_NATIVE_CORE_INDICATORS_MQH
#define AGI_NATIVE_CORE_INDICATORS_MQH
#include <Contracts/CoreIndicatorContract.mqh>
#include <Core/ClosedBarWindow.mqh>

bool NativeRejectCoreIndicators(NativeCoreIndicatorResult &result,const string reason)
  {
   result.valid=false;
   result.reason=reason;
   result.version=NATIVE_CORE_INDICATOR_VERSION;
   result.symbol="";
   result.timeframe="";
   result.bars_count=0;
   result.history_start_utc_msc=0;
   result.source_bar_timestamp_utc_msc=0;
   result.available_at_utc_msc=0;
   result.snapshot_utc_msc=0;
   result.clock_start_utc_msc=0;
   result.clock_resolution_msc=0;
   result.ema20=0.0;
   result.ema50=0.0;
   result.ema200=0.0;
   result.rsi14=0.0;
   result.atr14=0.0;
   result.execution_authorized=false;
   result.full_pipeline_verified=false;
   return false;
  }

bool NativeIndicatorNonnegative(const double value)
  {
   return MathIsValidNumber(value) && value>=0.0;
  }

bool NativeIndicatorAdd(const double left,const double right,double &sum)
  {
   sum=0.0;
   if(!NativeIndicatorNonnegative(left) || !NativeIndicatorNonnegative(right)) return false;
   if(left>DBL_MAX-right) return false;
   sum=left+right;
   return NativeIndicatorNonnegative(sum);
  }

bool NativeIndicatorRatio(const double numerator,const double denominator,double &ratio)
  {
   ratio=0.0;
   if(!NativeIndicatorNonnegative(numerator) || !MathIsValidNumber(denominator) || denominator<=0.0)
      return false;
   // Multiplication is bounded because denominator<1. Never evaluate an
   // overflowing quotient, including the extreme RSI case pandas saturates.
   if(denominator<1.0 && numerator>DBL_MAX*denominator) return false;
   ratio=numerator/denominator;
   return NativeIndicatorNonnegative(ratio);
  }

bool NativeIndicatorEwmStep(const double previous,const double current,
                            const double alpha,double &next)
  {
   next=0.0;
   if(!NativeIndicatorNonnegative(previous) || !NativeIndicatorNonnegative(current) ||
      !MathIsValidNumber(alpha) || alpha<=0.0 || alpha>=1.0) return false;
   // pandas avoids recomputing a constant value, preserving its exact bits.
   if(previous==current) { next=previous; return true; }
   double old_weight=1.0-alpha;
   // Both multipliers are in (0,1), so finite nonnegative inputs cannot overflow.
   double old_term=old_weight*previous;
   double new_term=alpha*current;
   double numerator=0.0,denominator=0.0;
   if(!NativeIndicatorAdd(old_term,new_term,numerator) ||
      !NativeIndicatorAdd(old_weight,alpha,denominator)) return false;
   return NativeIndicatorRatio(numerator,denominator,next);
  }

bool NativeIndicatorTrueRange(const NativeClosedBar &bar,const double previous_close,double &range)
  {
   range=0.0;
   // The caller already validated strictly positive finite OHLC. Subtracting
   // two such prices is bounded by DBL_MAX in magnitude.
   double high_low=bar.high-bar.low;
   double high_previous=MathAbs(bar.high-previous_close);
   double low_previous=MathAbs(bar.low-previous_close);
   if(!NativeIndicatorNonnegative(high_low) || !NativeIndicatorNonnegative(high_previous) ||
      !NativeIndicatorNonnegative(low_previous)) return false;
   range=MathMax(high_low,MathMax(high_previous,low_previous));
   return NativeIndicatorNonnegative(range);
  }

// Fixed, pure package: no terminal handles, time reads or strategy evaluation.
// Recompute from the complete selected prefix so its history origin is explicit.
bool NativeCalculateCoreIndicators(const NativeClosedBarRequest &request,
                                    const NativeClosedBar &bars[],NativeCoreIndicatorResult &result)
  {
   NativeRejectCoreIndicators(result,"INDICATOR_INPUT_INVALID");
   NativeClosedBarResult window;
   if(!NativeSelectClosedBars(request,bars,window)) return NativeRejectCoreIndicators(result,window.reason);
   int count=window.closed_count;
   if(count<200) return NativeRejectCoreIndicators(result,"INSUFFICIENT_INDICATOR_WARMUP");

   double ema20=window.closed_bars[0].close;
   double ema50=ema20,ema200=ema20;
   double atr14=window.closed_bars[0].high-window.closed_bars[0].low;
   double avg_gain=0.0,avg_loss=0.0;
   const double alpha14=1.0/14.0;
   if(!NativeIndicatorNonnegative(atr14)) return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
   for(int index=1;index<count;index++)
     {
      double close=window.closed_bars[index].close;
      double previous_close=window.closed_bars[index-1].close;
      double range=0.0;
      if(!NativeIndicatorTrueRange(window.closed_bars[index],previous_close,range))
         return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
      double delta=close-previous_close;
      if(!MathIsValidNumber(delta)) return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
      double gain=MathMax(delta,0.0),loss=MathMax(-delta,0.0);
      double next20=0.0,next50=0.0,next200=0.0,next_atr=0.0;
      if(!NativeIndicatorEwmStep(ema20,close,2.0/21.0,next20) ||
         !NativeIndicatorEwmStep(ema50,close,2.0/51.0,next50) ||
         !NativeIndicatorEwmStep(ema200,close,2.0/201.0,next200) ||
         !NativeIndicatorEwmStep(atr14,range,alpha14,next_atr))
         return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
      ema20=next20; ema50=next50; ema200=next200; atr14=next_atr;
      // The first real difference seeds RSI. There is no synthetic zero delta
      // at row zero and no simple-average seed after fourteen differences.
      if(index==1) { avg_gain=gain; avg_loss=loss; }
      else
        {
         double next_gain=0.0,next_loss=0.0;
         if(!NativeIndicatorEwmStep(avg_gain,gain,alpha14,next_gain) ||
            !NativeIndicatorEwmStep(avg_loss,loss,alpha14,next_loss))
            return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
         avg_gain=next_gain; avg_loss=next_loss;
        }
     }

   double rsi14=0.0;
   if(!NativeIndicatorNonnegative(avg_gain) || !NativeIndicatorNonnegative(avg_loss))
      return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
   if(avg_loss==0.0) rsi14=(avg_gain>0.0 ? 100.0 : 50.0);
   else if(avg_gain==0.0) rsi14=0.0;
   else
     {
      double relative_strength=0.0,denominator=0.0,discount=0.0;
      if(!NativeIndicatorRatio(avg_gain,avg_loss,relative_strength) ||
         !NativeIndicatorAdd(1.0,relative_strength,denominator) ||
         !NativeIndicatorRatio(100.0,denominator,discount))
         return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");
      rsi14=100.0-discount;
     }
   if(!MathIsValidNumber(ema20) || ema20<=0.0 || !MathIsValidNumber(ema50) || ema50<=0.0 ||
      !MathIsValidNumber(ema200) || ema200<=0.0 || !MathIsValidNumber(rsi14) || rsi14<0.0 || rsi14>100.0 ||
      !NativeIndicatorNonnegative(atr14)) return NativeRejectCoreIndicators(result,"INDICATOR_ARITHMETIC_INVALID");

   result.symbol=request.symbol;
   result.timeframe=window.timeframe;
   result.bars_count=count;
   result.history_start_utc_msc=window.closed_bars[0].timestamp_utc_msc;
   result.source_bar_timestamp_utc_msc=window.source_bar_timestamp_utc_msc;
   result.available_at_utc_msc=window.available_at_utc_msc;
   result.snapshot_utc_msc=request.snapshot_utc_msc;
   result.clock_start_utc_msc=request.clock_start_utc_msc;
   result.clock_resolution_msc=request.clock_resolution_msc;
   result.ema20=ema20; result.ema50=ema50; result.ema200=ema200;
   result.rsi14=rsi14; result.atr14=atr14;
   result.reason="CORE_INDICATORS_VALID";
   result.valid=true;
   return true;
  }
#endif
