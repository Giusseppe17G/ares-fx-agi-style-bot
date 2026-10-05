# Historical correctness diagnostic: 9aba352

Preserved as emitted by engine 0.3.0. These files are not a promotion package.
Source/config/input identifiers are recorded in summary.json; costs and broker
metadata are assumptions. The independent-candidate engine omits the full
portfolio risk pipeline and is not operationally eligible.

Subsequent metric review found that first calendar periods could be omitted
from worst-period returns and recovery factor used a percentage drawdown times
initial capital instead of the maximum monetary drawdown. Engine 0.3.1 fixes
these definitions. Do not interpret this historical report as corrected 0.3.1
metrics or overwrite it with later results. Trade fills and net profit are
unaffected by those metric-only corrections.

The inspected source CSVs contain zero spread on 18,845/20,000 EURUSD bars,
8/20,000 GBPUSD bars and 17,228/20,000 USDJPY bars. Zero could be a supplied quote
or missing cost evidence; this diagnostic does not resolve its meaning. All
three series are development data, not an untouched final holdout.
