#property strict
#property description "Pure closed-bar fixtures. Compilation does not execute assertions."
#include <Core/ClosedBarWindow.mqh>

// Fixtures supply every timestamp and numeric value; no terminal or file input.
int failures=0;
int checks=0;
void Check(const bool condition,const string label)
  {
   checks++;
   if(!condition) { failures++; Print("ASSERTION_FAILED: ",label); }
  }

#include "GeneratedClosedBarFixtures.mqh"

void CheckAliasedResultInput(void)
  {
   string timeframe="PERIOD_M15";
   Check(NativeNormalizeClosedBarTimeframe(timeframe,timeframe) && timeframe=="M15",
         "normalizer supports explicit in-place conversion");
   NativeClosedBar bars[1];
   bars[0].timestamp_utc_msc=1000000;
   bars[0].open=1.1; bars[0].high=1.2; bars[0].low=1.0; bars[0].close=1.15;
   bars[0].volume=0.0; bars[0].spread_points=0.0;
   NativeClosedBarRequest request={};
   request.symbol="EURUSD"; request.timeframe="M5";
   request.snapshot_utc_msc=1300000; request.clock_start_utc_msc=1300000;
   request.clock_resolution_msc=1; request.minimum_bars=1; request.max_snapshot_age_msc=5000;
   NativeClosedBarResult result;
   Check(NativeSelectClosedBars(request,bars,result),"alias setup is valid");
   Check(NativeSelectClosedBars(request,result.closed_bars,result),"result array may be reused as input");
   Check(result.valid && result.closed_count==1 && ArraySize(result.closed_bars)==1,
         "alias reuse preserves owned window");
   if(ArraySize(result.closed_bars)==1)
      Check(result.closed_bars[0].close==1.15,"alias reuse preserves original prices");
   Check(!result.execution_authorized && !result.full_pipeline_verified,"alias never authorizes execution");
   request.timeframe="PERIOD_M5";
   Check(!NativeSelectClosedBars(request,result.closed_bars,result),"selector does not normalize implicitly");
   Check(ArraySize(result.closed_bars)==0 && result.closed_count==0 && result.available_at_utc_msc==0,
         "rejected alias empties old output");
  }

void OnStart(void)
  {
   RunGeneratedClosedBarFixtures();
   CheckAliasedResultInput();
   PrintFormat("NATIVE_CLOSED_BAR_HARNESS checks=%d failures=%d",checks,failures);
  }
