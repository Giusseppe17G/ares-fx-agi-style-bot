#property strict
#property description "Pure risk gate fixtures. Compilation does not execute assertions."
#include <Risk/NativeRiskGate.mqh>

// Fixtures supply every input; no account, symbol, clock, file or trading API.
int failures=0;
int checks=0;
void Check(const bool condition,const string label)
  {
   checks++;
   if(!condition) { failures++; Print("ASSERTION_FAILED: ",label); }
  }

#include "GeneratedRiskGateFixtures.mqh"

// Hand-written lattice checks; tests/python verifies each literal with Decimal.
void CheckRiskLatticeArithmetic(void)
  {
   long units=0;
   Check(NativeRiskLatticeUnits(0.07,units) && units==7000000,"lattice 0.07");
   Check(NativeRiskLatticeUnits(150.012,units) && units==15001200000,"lattice 150.012");
   Check(!NativeRiskLatticeUnits(0.0000000015,units) && units==0,"off-lattice value rejected and cleared");
   Check(!NativeRiskLatticeUnits(1000000.01,units) && units==0,"lattice ceiling");
   Check(NativeRiskFloorUnits(0.06999999999999999,units) && units==6999999,"floor below boundary");
   Check(NativeRiskFloorUnits(7.142857142857143,units) && units==714285714,"floor repeating quotient");
   Check(NativeRiskFloorUnits(0.29,units) && units==29000000,"floor binary-inexact decimal");
   Check(NativeRiskNormalizeLotDown(0.06999999999999999,1000000,10000000000,1000000)==0.06,"normalize never rounds up");
   Check(NativeRiskNormalizeLotDown(1000000000.0,1000000,300000000,1000000)==3.0,"normalize caps at maximum");
   Check(NativeRiskNormalizeLotDown(0.0099,1000000,10000000000,1000000)==0.0,"normalize below minimum");
  }

void OnStart(void)
  {
   RunGeneratedRiskGateFixtures();
   CheckRiskLatticeArithmetic();
   PrintFormat("NATIVE_RISK_GATE_HARNESS checks=%d failures=%d",checks,failures);
  }
