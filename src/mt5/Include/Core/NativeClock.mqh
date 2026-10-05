#ifndef AGI_NATIVE_CLOCK_MQH
#define AGI_NATIVE_CLOCK_MQH
#include <Core/ObservationPolicy.mqh>

class NativeUtcClock
  {
private:
   datetime m_previous;
public:
   NativeUtcClock(void) { m_previous=0; }
   bool Read(datetime &now_utc,string &reason)
     {
      now_utc=0;
      // In the tester TimeGMT equals simulated server time, not verified UTC.
      if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION))
        { reason="TESTER_UTC_UNAVAILABLE"; return false; }
      datetime observed=TimeGMT();
      if(observed<=0 || (m_previous>0 && observed<m_previous))
        { reason="UTC_CLOCK_INVALID"; return false; }
      m_previous=observed;
      now_utc=observed;
      reason="HOST_COMPUTED_UTC";
      return true;
     }
  };
#endif
