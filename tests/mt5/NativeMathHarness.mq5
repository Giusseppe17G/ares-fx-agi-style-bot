#property strict
#property version "1.00"
#property description "Synthetic fixture wrapper for isolated mathematical testing only."

// Reuse the original assertion bodies without changing their sources.
// SHA256 at wrapper creation (the runner must bind the complete include graph):
// ObservationPolicyHarness.mq5 16a791f0136bf09346ddef65f8a69346a3478cd8bba547d448369c7b45efc4c0
// ClosedBarWindowHarness.mq5 e4dedce9057337a61d2a00a0c46d72187d2a5a908b62b1f4ca324526ce859271
// CoreIndicatorsHarness.mq5 097ed6d3b9ffafd14a44fdc844f8c209492a37317bf3e30474c938b65cea7ea3
// GeneratedClosedBarFixtures.mqh ebfc995ea5da01c46155d0712b0acb70d0cf79d99e5de484f6f6563fc5ced734
// GeneratedCoreIndicatorFixtures.mqh 2bdf82a62837fcc907f175c6e9f94c6a6ee69ccf79ec9b05f1b9b7d8d001d649

#define OnStart NativeMathRunObserver
#define Check NativeMathObserverCheck
#define checks NativeMathObserverChecks
#define failures NativeMathObserverFailures
#include "ObservationPolicyHarness.mq5"
#undef failures
#undef checks
#undef Check
#undef OnStart

#define OnStart NativeMathRunClosedBars
#define Check NativeMathClosedBarsCheck
#define checks NativeMathClosedBarsChecks
#define failures NativeMathClosedBarsFailures
#include "ClosedBarWindowHarness.mq5"
#undef failures
#undef checks
#undef Check
#undef OnStart

#define OnStart NativeMathRunCoreIndicators
#define Check NativeMathCoreIndicatorsCheck
#define checks NativeMathCoreIndicatorsChecks
#define failures NativeMathCoreIndicatorsFailures
#include "CoreIndicatorsHarness.mq5"
#undef failures
#undef checks
#undef Check
#undef OnStart

const int NATIVE_MATH_EXPECTED_OBSERVER=31;
const int NATIVE_MATH_EXPECTED_CLOSED_BARS=1103;
const int NATIVE_MATH_EXPECTED_CORE_INDICATORS=1348;
const int NATIVE_MATH_EXPECTED_TOTAL=2482;
bool NativeMathInitialized=false;
bool NativeMathTesterCalled=false;
bool NativeMathSuitesCompleted=false;
int NativeMathStagesCompleted=0;
int NativeMathWrapperFailures=0;
int NativeMathTicks=0;

bool NativeMathContextAllowed(void)
  {
   // No public MQLInfoInteger property reports the tester's Model value.
   // Model=3 is a separately verified runner requirement, never inferred here.
   return MQLInfoInteger(MQL_TESTER)!=0 &&
          MQLInfoInteger(MQL_OPTIMIZATION)==0 &&
          MQLInfoInteger(MQL_VISUAL_MODE)==0 &&
          MQLInfoInteger(MQL_FORWARD)==0 &&
          MQLInfoInteger(MQL_FRAME_MODE)==0;
  }

int NativeMathTotalChecks(void)
  {
   return NativeMathObserverChecks+NativeMathClosedBarsChecks+NativeMathCoreIndicatorsChecks;
  }

int NativeMathTotalFailures(void)
  {
   return NativeMathObserverFailures+NativeMathClosedBarsFailures+NativeMathCoreIndicatorsFailures;
  }

bool NativeMathPassed(void)
  {
   return NativeMathInitialized && NativeMathTesterCalled && NativeMathSuitesCompleted &&
          NativeMathStagesCompleted==3 && NativeMathWrapperFailures==0 && NativeMathTicks==0 &&
          NativeMathObserverChecks==NATIVE_MATH_EXPECTED_OBSERVER &&
          NativeMathClosedBarsChecks==NATIVE_MATH_EXPECTED_CLOSED_BARS &&
          NativeMathCoreIndicatorsChecks==NATIVE_MATH_EXPECTED_CORE_INDICATORS &&
          NativeMathTotalChecks()==NATIVE_MATH_EXPECTED_TOTAL && NativeMathTotalFailures()==0;
  }

void NativeMathRecordStage(const string stage,const int actual_checks,
                           const int expected_checks,const int actual_failures)
  {
   NativeMathStagesCompleted++;
   if(actual_checks!=expected_checks || actual_failures<0)
      NativeMathWrapperFailures++;
   PrintFormat("AGI_NATIVE_MATH_STAGE name=%s checks=%d failures=%d expected_checks=%d accepted=%d execution_authorized=false full_pipeline_verified=false",
               stage,actual_checks,actual_failures,expected_checks,
               actual_checks==expected_checks && actual_failures==0 ? 1 : 0);
  }

int OnInit(void)
  {
   if(!NativeMathContextAllowed() || NativeMathInitialized)
     {
      NativeMathWrapperFailures++;
      Print("AGI_NATIVE_MATH_REJECT reason=TEST_CONTEXT_REQUIRED execution_authorized=false full_pipeline_verified=false");
      return INIT_FAILED;
     }
   NativeMathInitialized=true;
   PrintFormat("AGI_NATIVE_MATH_BEGIN version=native_math_harness_v1 expected_checks=%d model_required=3 model_verified_in_mql=false execution_authorized=false full_pipeline_verified=false",
               NATIVE_MATH_EXPECTED_TOTAL);
   return INIT_SUCCEEDED;
  }

void OnTick(void)
  {
   // Unexpected tick delivery rejects the run; no quote is read or used.
   if(NativeMathTicks==0)
     {
      NativeMathWrapperFailures++;
      Print("AGI_NATIVE_MATH_REJECT reason=UNEXPECTED_TICK execution_authorized=false full_pipeline_verified=false");
     }
   if(NativeMathTicks<2147483647) NativeMathTicks++;
  }

double OnTester(void)
  {
   if(!NativeMathInitialized || !NativeMathContextAllowed() || NativeMathTesterCalled ||
      NativeMathTicks!=0 || NativeMathWrapperFailures!=0)
     {
      NativeMathWrapperFailures++;
      Print("AGI_NATIVE_MATH_REJECT reason=TESTER_LIFECYCLE_INVALID execution_authorized=false full_pipeline_verified=false");
      return 0.0;
     }
   NativeMathTesterCalled=true;
   NativeMathRunObserver();
   NativeMathRecordStage("observer",NativeMathObserverChecks,NATIVE_MATH_EXPECTED_OBSERVER,NativeMathObserverFailures);
   NativeMathRunClosedBars();
   NativeMathRecordStage("closed_bars",NativeMathClosedBarsChecks,NATIVE_MATH_EXPECTED_CLOSED_BARS,NativeMathClosedBarsFailures);
   NativeMathRunCoreIndicators();
   NativeMathRecordStage("core_indicators",NativeMathCoreIndicatorsChecks,NATIVE_MATH_EXPECTED_CORE_INDICATORS,NativeMathCoreIndicatorsFailures);
   NativeMathSuitesCompleted=true;
   if(!NativeMathContextAllowed()) NativeMathWrapperFailures++;
   PrintFormat("AGI_NATIVE_MATH_TOTAL checks=%d failures=%d ticks=%d accepted=%d wrapper_failures=%d stages=%d expected_checks=%d execution_authorized=false full_pipeline_verified=false",
               NativeMathTotalChecks(),NativeMathTotalFailures(),NativeMathTicks,NativeMathPassed() ? 1 : 0,
               NativeMathWrapperFailures,NativeMathStagesCompleted,NATIVE_MATH_EXPECTED_TOTAL);
   // A logical assertion result, never a profit or strategy selection metric.
   return NativeMathPassed() ? 1.0 : 0.0;
  }

void OnDeinit(const int reason)
  {
   const bool completed=NativeMathTesterCalled && NativeMathSuitesCompleted && NativeMathStagesCompleted==3;
   PrintFormat("AGI_NATIVE_MATH_COMPLETE checks=%d failures=%d ticks=%d accepted=%d reason=%d completed=%d wrapper_failures=%d stages=%d expected_checks=%d model_verified_in_mql=false execution_authorized=false full_pipeline_verified=false",
               NativeMathTotalChecks(),NativeMathTotalFailures(),NativeMathTicks,NativeMathPassed() ? 1 : 0,
               reason,completed ? 1 : 0,NativeMathWrapperFailures,NativeMathStagesCompleted,NATIVE_MATH_EXPECTED_TOTAL);
  }
