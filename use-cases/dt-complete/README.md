
# DT-Complete

A demonstration of a complete digital twin:

2 sensors + 3 surrogates* / physics entities

Sensors:
- M3DC1 Mock sensor
- Random Value sensor

Three physical entities:
- M3DC1 Investigator
- Runs a M3DC1 Investigator
- Runs a DEMO_AGENT Agent (a simple pass through)
- Runs a NEGATIVE_Agent Agent (simply computes the negative of sensor input)

> *Technically, the M3DC1 trains two surrogates and then picks the best one.


**Digital Twin Description Graph:**
```

M3DC1 Mock sensor --> M3DC1 Investigator --
                                           \ 
                                            --(JOIN)--> DEMO Agent --> OUT  
RAND_VAL sensor  ---> NEGATIVE_Agent ------/

```



## To run:

1. Install the digital twins library:

``` bash
git clone https://github.com/radical-cybertools/digital.twins

# this is for the plain DT framework without all the as-a-service changes
git checkout release/vanilla-framework
pip install . 
```

2. Start up your sensors: `python3 m3dc1_mock_sensor.py` and `python3 rand_sensor.py`
3. Start up the PUB/SUB streaming broker: `python3 local_broker.py`
4. Finally, run `python3 run_me.py`
