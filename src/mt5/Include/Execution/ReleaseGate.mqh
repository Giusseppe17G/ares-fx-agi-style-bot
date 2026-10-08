#ifndef AGI_NATIVE_RELEASE_GATE_MQH
#define AGI_NATIVE_RELEASE_GATE_MQH

// No request type or executable adapter exists in this native release.
bool NativeExecutionGate(string &reason)
  {
   reason="EXECUTION_NOT_RELEASED";
   return false;
  }
#endif
