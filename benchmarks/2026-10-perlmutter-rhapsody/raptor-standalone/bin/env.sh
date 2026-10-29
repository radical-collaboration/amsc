#!/bin/bash
# Environment for the standalone (pilot-free) raptor + rhapsody backend.
module load python/3.13-26.8.1
export RAPTOR_STANDALONE=/pscratch/sd/m/merzky/radical/raptor-standalone
export RHAPSODY_SRC=/pscratch/sd/m/merzky/radical/rhapsody/src
export VE_RAPTOR=$RAPTOR_STANDALONE/ve.raptor
export PYTHONPATH=$RHAPSODY_SRC:$RAPTOR_STANDALONE:$PYTHONPATH
export PYTHON=$VE_RAPTOR/bin/python
# radical.utils: keep logging quiet/fast for benchmarking
export RADICAL_LOG_LVL=ERROR
export RADICAL_REPORT=FALSE
