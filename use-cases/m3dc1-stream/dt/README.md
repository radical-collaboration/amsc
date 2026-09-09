

# The M3DC1-stream (aka SPARC-stream) ported over to the Digital Twin framework.

Items:
- `sensor_daemon.py` --> `dt/sensor.py`
- `amsc_stream.py` --> `dt/amsc_investigator.py`

Other:
`dt/run_me.py`
`dt/dtypes.py`

The digital twin framework handles sensor streams directly, so the demo defers
in-stream data movement to the digital twin framework. (Data is small enough where
this works).


## To run:

1. Install the digital twins library:

``` bash
git clone https://github.com/radical-cybertools/digital.twins

# this is for the plain DT framework without all the as-a-service changes
git checkout release/vanilla-framework
pip install . 
```

2. Run in one terminal `python3 sensor.py`
3. Run in a second terminal `python3 local_broker.py`
4. Finally, in a third terminal, run `python3 run_me.py`
