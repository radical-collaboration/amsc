from digitaltwin.components import DataType, JoinDataType

#############################
# Complete Digital Twin demo DATA_TYPES
#############################

# use the M3DC1 sensor and prediction data types
from m3dc1.m3dc1_dtypes import *

# use the NEGATIVE_Agent sensors and data types
from negative_agent.neg_dtypes import *

# The JOIN output DataType
JOIN_NEG_M3DC1 = JoinDataType([M3DC1_PREDICTION, NEG_PREDICTION])

# use the DEMO Agent data types
from demo_agent.demo_dtypes import *
