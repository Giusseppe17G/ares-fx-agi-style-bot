#property strict
#property description "Pure core indicator fixtures. Compilation does not execute assertions."
#include <Core/CoreIndicators.mqh>

// Synthetic timestamps and values are compiled in; no market/terminal input.
int failures=0;
int checks=0;
void Check(const bool condition,const string label)
  {
   checks++;
   if(!condition) { failures++; Print("ASSERTION_FAILED: ",label); }
  }

#include "GeneratedCoreIndicatorFixtures.mqh"

void OnStart(void)
  {
   RunGeneratedCoreIndicatorFixtures();
   PrintFormat("NATIVE_CORE_INDICATORS_HARNESS checks=%d failures=%d",checks,failures);
  }
